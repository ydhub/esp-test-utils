import pytest

import esptest.common.compat_typing as t
from esptest.devices.multimeter import Multimeter, get_multimeter_specific
from esptest.devices.multimeter import factory as factory_mod
from esptest.devices.multimeter.base import DeviceInfo, MultimeterBackend, registered_backends


def test_sample_rate_updates_sampling_frequency() -> None:
    mm = Multimeter(backend='gpib', address=22)
    mm.sample_rate = 0.0001
    assert mm.sampling_frequency == 10000


@pytest.mark.parametrize('bad_rate', [0, 0.0, -0.001])
def test_sample_rate_rejects_non_positive(bad_rate: float) -> None:
    mm = Multimeter(backend='gpib', address=22)
    with pytest.raises(ValueError, match='sample_rate must be a positive'):
        mm.sample_rate = bad_rate
    assert mm.sample_rate is None
    assert mm.sampling_frequency is None


def test_constructor_rejects_non_positive_sample_rate() -> None:
    with pytest.raises(ValueError, match='sample_rate must be a positive'):
        Multimeter(backend='gpib', address=22, sample_rate=0)


def test_sample_rate_none_clears_sampling_frequency() -> None:
    mm = Multimeter(backend='gpib', address=22, sample_rate=0.001)
    assert mm.sampling_frequency == 1000
    mm.sample_rate = None
    assert mm.sampling_frequency is None


def test_device_start_requires_sample_rate() -> None:
    mm = Multimeter(backend='gpib', address=22)
    with pytest.raises(ValueError):
        mm.device_start()


def test_measure_lifecycle_with_fake_backend() -> None:
    calls = []  # type: t.List[t.Any]

    class FakeBackend(MultimeterBackend):
        backend_name = 'fake_lifecycle'

        def __init__(self, **kwargs: t.Any) -> None:
            self.kwargs = kwargs

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            return [DeviceInfo(backend='fake_lifecycle', address=1)]

        def open(self) -> None:
            calls.append('open')

        def close(self) -> None:
            calls.append('close')

        def prepare(self, sample_rate_s: float) -> None:
            calls.append(('prepare', sample_rate_s))

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            calls.append(('measure', duration_s, dict(kwargs)))
            return [1.0, 2.0]

        def measure_once(self, measure_type: str) -> float:
            calls.append(('once', measure_type))
            return 0.0015

    try:
        mm = Multimeter(backend='fake_lifecycle', sample_rate=0.0001, address=1)
        mm.device_start()
        assert 'open' in calls
        assert ('prepare', 0.0001) in calls

        data = mm.measure_current(0.2, max_value=0.1)
        assert data == [1.0, 2.0]
        assert ('measure', 0.2, {'max_value': 0.1}) in calls

        assert mm.measure_current_once() == 0.0015
        assert mm.measure_voltage_once() == 0.0015
        assert ('once', 'IDC') in calls
        assert ('once', 'VDC') in calls

        mm.device_close()
        assert 'close' in calls
        # idempotent close
        mm.device_close()
    finally:
        registered_backends().pop('fake_lifecycle', None)


def test_get_multimeter_specific_not_one_match(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch the module object (string paths break on Py3.7 + esptest.__init__ import).
    monkeypatch.setattr(factory_mod, 'list_multimeters', lambda **kw: [])
    with pytest.raises(RuntimeError):
        get_multimeter_specific(backend='gpib')


def test_device_start_closes_existing_backend() -> None:
    calls = []  # type: t.List[t.Any]

    class FakeBackend(MultimeterBackend):
        backend_name = 'fake_restart'

        def __init__(self, **kwargs: t.Any) -> None:
            calls.append(('init', dict(kwargs)))

        @classmethod
        def list_devices(cls, **filters: t.Any) -> t.List[DeviceInfo]:
            return [DeviceInfo(backend='fake_restart', address=1)]

        def open(self) -> None:
            calls.append('open')

        def close(self) -> None:
            calls.append('close')

        def prepare(self, sample_rate_s: float) -> None:
            calls.append(('prepare', sample_rate_s))

        def measure_current_ma(self, duration_s: float, **kwargs: t.Any) -> t.List[float]:
            return []

    try:
        mm = Multimeter(backend='fake_restart', sample_rate=0.0001, address=1)
        mm.device_start()
        mm.device_start()
        assert calls.count('open') == 2
        assert calls.count('close') == 1
        first_open = calls.index('open')
        first_close = calls.index('close')
        second_open = calls.index('open', first_open + 1)
        assert first_open < first_close < second_open
    finally:
        registered_backends().pop('fake_restart', None)


def test_constructor_sets_log_path_and_sample_rate() -> None:
    mm = Multimeter('/tmp/logs', 0.0001, backend='gpib', address=22)
    assert mm.log_path == '/tmp/logs'
    assert mm.sample_rate == 0.0001
    assert mm.sampling_frequency == 10000
