import pytest

import esptest.common.compat_typing as t
from esptest.devices.multimeter import gpib as gpib_mod
from esptest.devices.multimeter.base import MultimeterError, get_backend_class
from esptest.devices.multimeter.gpib import (
    MAX_SAMPLE_COUNT,
    SAMPLE_TIME_34465A,
    GpibBackend,
)
from esptest.devices.multimeter.transport.base import GPIBTransport


class FakeGPIBTransport(GPIBTransport):
    """Minimal scripted transport for GpibBackend unit tests."""

    def __init__(self, replies: t.Optional[t.Dict[str, str]] = None) -> None:
        self.writes = []  # type: t.List[str]
        self._replies = dict(replies or {})
        self.closed = False

    def write(self, cmd: str) -> None:
        assert not self.closed
        self.writes.append(cmd)

    def ask(self, cmd: str) -> str:
        assert not self.closed
        self.writes.append(cmd)
        if cmd not in self._replies:
            raise KeyError('no scripted reply for %r' % cmd)
        return self._replies[cmd]

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_transport() -> FakeGPIBTransport:
    return FakeGPIBTransport(
        replies={
            '*OPC?': '1',
            'FETC?': '0.001,0.002',
            'MEAS:CURR:DC? MAX': '0.0015',
        }
    )


def test_gpib_backend_auto_registers() -> None:
    assert get_backend_class('gpib') is GpibBackend


def test_measure_current_ma_scpi_and_ma_scale(fake_transport: FakeGPIBTransport) -> None:
    backend = GpibBackend(transport=fake_transport, sample_time=SAMPLE_TIME_34465A)
    backend.prepare(0.001)
    data = backend.measure_current_ma(duration_s=0.002, max_value=0.1)
    # sample_num = int(0.002/0.001)=2
    assert data == pytest.approx([1.0, 2.0])  # mA
    assert any('CONF:CURR:DC' in w or w.startswith('CONF:CURR') for w in fake_transport.writes)
    assert 'SAMP:COUN 2' in fake_transport.writes
    assert '*TRG' in fake_transport.writes
    assert 'FETC?' in fake_transport.writes


def test_sample_rate_too_small_raises(fake_transport: FakeGPIBTransport) -> None:
    backend = GpibBackend(transport=fake_transport, sample_time=SAMPLE_TIME_34465A)
    backend.prepare(SAMPLE_TIME_34465A / 2.0)
    with pytest.raises(ValueError, match='sample rate'):
        backend.measure_current_ma(duration_s=0.001, max_value=0.1)


def test_sample_count_exceeds_max_raises(fake_transport: FakeGPIBTransport) -> None:
    backend = GpibBackend(transport=fake_transport, sample_time=SAMPLE_TIME_34465A)
    sample_rate = 0.001
    backend.prepare(sample_rate)
    duration_s = sample_rate * (MAX_SAMPLE_COUNT + 1)
    with pytest.raises(ValueError, match='sample count'):
        backend.measure_current_ma(duration_s=duration_s, max_value=0.1)


def test_unknown_kwargs_typeerror(fake_transport: FakeGPIBTransport) -> None:
    backend = GpibBackend(transport=fake_transport, sample_time=SAMPLE_TIME_34465A)
    backend.prepare(0.001)
    with pytest.raises(TypeError):
        backend.measure_current_ma(duration_s=0.002, max_value=0.1, not_a_param=1)


def test_list_devices_rejects_joulescope_filters() -> None:
    with pytest.raises(NotImplementedError):
        GpibBackend.list_devices(serial_number='x')
    with pytest.raises(NotImplementedError):
        GpibBackend.list_devices(path='/dev/js0')


def test_sample_count_below_one_raises(fake_transport: FakeGPIBTransport) -> None:
    backend = GpibBackend(transport=fake_transport, sample_time=SAMPLE_TIME_34465A)
    backend.prepare(0.001)
    with pytest.raises(ValueError, match='sample count is below 1'):
        backend.measure_current_ma(duration_s=0.0005, max_value=0.1)
    # No SCPI configuration must reach the instrument for an invalid SAMP:COUN.
    assert fake_transport.writes == []


def test_default_opc_timeout_scales_with_duration() -> None:
    assert GpibBackend.default_opc_timeout_s(0.5) == 30
    assert GpibBackend.default_opc_timeout_s(30.0) == 40
    assert GpibBackend.default_opc_timeout_s(120.5) == 131


def test_measure_uses_duration_based_opc_timeout(
    monkeypatch: pytest.MonkeyPatch,
    fake_transport: FakeGPIBTransport,
) -> None:
    seen = []  # type: t.List[int]

    def mock_is_busy(_self: GpibBackend, timeout: int = 10) -> bool:
        seen.append(timeout)
        return False

    monkeypatch.setattr(GpibBackend, 'is_busy', mock_is_busy)
    backend = GpibBackend(transport=fake_transport, sample_time=SAMPLE_TIME_34465A)
    backend.prepare(0.01)
    backend.measure_current_ma(duration_s=120.0, max_value=0.1)
    assert seen == [130]


def test_measure_honours_explicit_opc_timeout(
    monkeypatch: pytest.MonkeyPatch,
    fake_transport: FakeGPIBTransport,
) -> None:
    seen = []  # type: t.List[int]

    def mock_is_busy(_self: GpibBackend, timeout: int = 10) -> bool:
        seen.append(timeout)
        return False

    monkeypatch.setattr(GpibBackend, 'is_busy', mock_is_busy)
    backend = GpibBackend(transport=fake_transport, sample_time=SAMPLE_TIME_34465A)
    backend.prepare(0.01)
    backend.measure_current_ma(duration_s=120.0, max_value=0.1, opc_timeout_s=5)
    assert seen == [5]


def test_list_devices_skips_device_without_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SilentTransport(FakeGPIBTransport):
        def __init__(self) -> None:
            super().__init__(replies={})

        def ask(self, cmd: str) -> str:
            raise OSError('no reply from pad')

    probe = SilentTransport()
    monkeypatch.setattr(gpib_mod, 'open_gpib', lambda **_kwargs: probe)
    assert GpibBackend.list_devices() == []
    assert probe.closed is True


def test_list_devices_skips_empty_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = FakeGPIBTransport(replies={'*IDN?': ''})
    monkeypatch.setattr(gpib_mod, 'open_gpib', lambda **_kwargs: probe)
    assert GpibBackend.list_devices() == []
    assert probe.closed is True


def test_list_devices_returns_empty_on_open_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**_kwargs: t.Any) -> t.Any:
        raise OSError('no hardware')

    # Patch the module object (string paths break on Py3.7 + esptest.__init__ import).
    monkeypatch.setattr(gpib_mod, 'open_gpib', boom)
    assert GpibBackend.list_devices() == []


def test_list_devices_auto_discover_fills_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProbeTransport(FakeGPIBTransport):
        def __init__(self) -> None:
            super().__init__(replies={'*IDN?': 'KEYSIGHT,34465A'})
            self._address = 22

        @property
        def address(self) -> int:
            return self._address

    probe = ProbeTransport()

    def mock_open_gpib(**_kwargs: t.Any) -> ProbeTransport:
        return probe

    monkeypatch.setattr(gpib_mod, 'open_gpib', mock_open_gpib)
    infos = GpibBackend.list_devices()
    assert len(infos) == 1
    assert infos[0].address == 22
    assert infos[0].identity == 'KEYSIGHT,34465A'
    assert probe.closed is True


def test_list_devices_auto_discover_fills_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProbeTransport(FakeGPIBTransport):
        def __init__(self) -> None:
            super().__init__(replies={'*IDN?': 'KEYSIGHT,34401A'})
            self._resource = 'GPIB0::7::INSTR'

        @property
        def resource(self) -> str:
            return self._resource

    probe = ProbeTransport()

    def mock_open_gpib(**_kwargs: t.Any) -> ProbeTransport:
        return probe

    monkeypatch.setattr(gpib_mod, 'open_gpib', mock_open_gpib)
    infos = GpibBackend.list_devices()
    assert len(infos) == 1
    assert infos[0].resource == 'GPIB0::7::INSTR'
    assert infos[0].identity == 'KEYSIGHT,34401A'
    assert probe.closed is True


def test_busy_timeout_raises_multimeter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGPIBTransport(replies={'*OPC?': '0'})
    monkeypatch.setattr(gpib_mod.time, 'sleep', lambda _s: None)
    backend = GpibBackend(transport=fake, sample_time=SAMPLE_TIME_34465A)
    backend.prepare(0.001)
    with pytest.raises(MultimeterError, match='busy'):
        backend.measure_current_ma(duration_s=0.002, max_value=0.1, opc_timeout_s=2)


def test_open_skipped_when_transport_injected(fake_transport: FakeGPIBTransport) -> None:
    backend = GpibBackend(transport=fake_transport)
    backend.open()  # should be a no-op; no open_gpib call
    backend.close()
    assert fake_transport.closed is True
    assert backend._transport is fake_transport


def test_close_then_open_reopens_non_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    open_count = {'n': 0}

    def mock_open_gpib(**_kwargs: t.Any) -> FakeGPIBTransport:
        open_count['n'] += 1
        return FakeGPIBTransport()

    monkeypatch.setattr(gpib_mod, 'open_gpib', mock_open_gpib)
    backend = GpibBackend(address=5)
    backend.open()
    assert open_count['n'] == 1
    backend.close()
    backend.open()
    assert open_count['n'] == 2


def test_measure_once_current(fake_transport: FakeGPIBTransport) -> None:
    backend = GpibBackend(transport=fake_transport)
    # measure_once returns instrument units (amperes), like ats-n2
    assert backend.measure_once('IDC') == pytest.approx(0.0015)
