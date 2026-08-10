import builtins

import pytest

import esptest.common.compat_typing as t
from esptest.devices.multimeter.transport import factory as factory_mod
from esptest.devices.multimeter.transport import linux as linux_mod
from esptest.devices.multimeter.transport import windows as windows_mod
from esptest.devices.multimeter.transport.base import GPIBTransport
from esptest.devices.multimeter.transport.factory import open_gpib
from esptest.devices.multimeter.transport.linux import LinuxGpibTransport
from esptest.devices.multimeter.transport.windows import VisaGpibTransport


class FakeGPIBTransport(GPIBTransport):
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


def test_fake_write_ask_close() -> None:
    fake = FakeGPIBTransport(replies={'*IDN?': 'KEYSIGHT,34465A'})
    fake.write('*RST')
    assert fake.ask('*IDN?') == 'KEYSIGHT,34465A'
    fake.close()
    assert fake.closed is True
    assert fake.writes == ['*RST', '*IDN?']


def test_transport_module_docstring_marks_draft() -> None:
    import esptest.devices.multimeter.transport as tr

    assert 'Draft' in (tr.__doc__ or '')


def test_open_gpib_dispatches_linux_address(monkeypatch: pytest.MonkeyPatch) -> None:
    created = []  # type: t.List[int]

    class Stub(GPIBTransport):
        def __init__(self, address: t.Optional[int] = None) -> None:
            created.append(address)  # type: ignore[arg-type]

        def write(self, cmd: str) -> None:
            pass

        def ask(self, cmd: str) -> str:
            return ''

        def close(self) -> None:
            pass

    # Patch module objects (string paths break on Py3.7 + esptest.__init__ import).
    monkeypatch.setattr(factory_mod.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(factory_mod, 'LinuxGpibTransport', Stub)
    dev = open_gpib(address=22)
    assert isinstance(dev, Stub)
    assert created == [22]


def test_open_gpib_windows_uses_visa(monkeypatch: pytest.MonkeyPatch) -> None:
    created = []  # type: t.List[t.Tuple[t.Optional[str], t.Optional[int]]]

    class Stub(GPIBTransport):
        def __init__(
            self,
            resource: t.Optional[str] = None,
            address: t.Optional[int] = None,
        ) -> None:
            created.append((resource, address))

        def write(self, cmd: str) -> None:
            pass

        def ask(self, cmd: str) -> str:
            return ''

        def close(self) -> None:
            pass

    monkeypatch.setattr(factory_mod.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(factory_mod, 'VisaGpibTransport', Stub)
    open_gpib(resource='GPIB0::22::INSTR')
    assert created == [('GPIB0::22::INSTR', None)]


def test_linux_gpib_ask_decodes_bytes_and_strips(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockGpibInst:
        def __init__(self, _board: int, _pad: int) -> None:
            pass

        def write(self, _cmd: str) -> None:
            pass

        def read(self, _size: int) -> bytes:
            return b'KEYSIGHT,34465A\r\n'

        def close(self) -> None:
            pass

    class MockGpibMod:
        Gpib = MockGpibInst

    monkeypatch.setattr(linux_mod, '_import_gpib', lambda: MockGpibMod)
    transport = LinuxGpibTransport(address=5)
    assert transport.ask('*IDN?') == 'KEYSIGHT,34465A'


def test_linux_gpib_ask_decodes_latin1_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockGpibInst:
        def __init__(self, _board: int, _pad: int) -> None:
            pass

        def write(self, _cmd: str) -> None:
            pass

        def read(self, _size: int) -> bytes:
            return b'\xff\r\n'

        def close(self) -> None:
            pass

    class MockGpibMod:
        Gpib = MockGpibInst

    monkeypatch.setattr(linux_mod, '_import_gpib', lambda: MockGpibMod)
    transport = LinuxGpibTransport(address=5)
    assert transport.ask('READ?') == '\xff'


def test_visa_gpib_ask_decodes_bytes_and_strips(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockDevice:
        def query(self, _cmd: str) -> bytes:
            return b'  1.234E+00  \r\n'

        def close(self) -> None:
            pass

    class MockResourceManager:
        def open_resource(self, _resource: str) -> MockDevice:
            return MockDevice()

    class MockPyvisaMod:
        ResourceManager = MockResourceManager

    monkeypatch.setattr(windows_mod, '_import_pyvisa', lambda: MockPyvisaMod)
    transport = VisaGpibTransport(resource='GPIB0::5::INSTR')
    assert transport.ask('MEAS?') == '  1.234E+00'
    assert transport.resource == 'GPIB0::5::INSTR'


def test_visa_close_closes_resource_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = {'device': False, 'rm': False}

    class MockDevice:
        def close(self) -> None:
            closed['device'] = True

    class MockResourceManager:
        def open_resource(self, _resource: str) -> MockDevice:
            return MockDevice()

        def close(self) -> None:
            closed['rm'] = True

    class MockPyvisaMod:
        ResourceManager = MockResourceManager

    monkeypatch.setattr(windows_mod, '_import_pyvisa', lambda: MockPyvisaMod)
    transport = VisaGpibTransport(resource='GPIB0::5::INSTR')
    transport.close()
    assert closed['device'] is True
    assert closed['rm'] is True
    assert transport._rm is None
    assert transport._device is None


def test_linux_gpib_exposes_address_property(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockGpibInst:
        def __init__(self, _board: int, _pad: int) -> None:
            pass

        def write(self, _cmd: str) -> None:
            pass

        def read(self, _size: int) -> bytes:
            return b'ok'

        def close(self) -> None:
            pass

    class MockGpibMod:
        Gpib = MockGpibInst

    monkeypatch.setattr(linux_mod, '_import_gpib', lambda: MockGpibMod)
    transport = LinuxGpibTransport(address=11)
    assert transport.address == 11


def test_find_address_closes_probe_handles() -> None:
    closed = []  # type: t.List[int]

    class MockGpibInst:
        def __init__(self, _board: int, pad: int) -> None:
            self.pad = pad

        def write(self, _cmd: str) -> None:
            if self.pad != 3:
                raise OSError('no device at pad %d' % self.pad)

        def read(self, _size: int) -> bytes:
            return b'ok'

        def close(self) -> None:
            closed.append(self.pad)

    class MockGpibMod:
        Gpib = MockGpibInst

    assert LinuxGpibTransport._find_address(MockGpibMod) == 3
    assert closed == [0, 1, 2, 3]


def test_linux_gpib_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def mock_import(name: str, *args: t.Any, **kwargs: t.Any) -> t.Any:
        if name == 'Gpib':
            raise ImportError('No module named Gpib')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', mock_import)
    with pytest.raises(ImportError, match='linux-gpib \\(import Gpib\\) is required'):
        LinuxGpibTransport(address=5)
