import contextlib
from pathlib import Path

import pytest
import serial

import esptest.common.compat_typing as t
from esptest.adapter.port.serial_port import SerialExt, SerialPort, SerialPortMixin, SerMixin


class _DummySerial(serial.Serial):
    pass


class _DummySerialBase(serial.SerialBase):
    pass


class _ReopenHarness(SerialPortMixin):
    def __init__(self, serial_config: t.Dict[str, t.Any]) -> None:
        self._serial_config = serial_config
        self._raw_port: t.Optional[serial.SerialBase] = None

    @property
    def serial(self) -> t.Optional[serial.SerialBase]:
        return self._raw_port

    @serial.setter
    def serial(self, serial_instance: 't.Optional[serial.SerialBase]') -> None:
        self._raw_port = serial_instance


class _ChangeConfigHarness:
    """Minimal host for SerialPortMixin.change_serial_config (unbound call)."""

    def __init__(self, raw_port: t.Optional[serial.SerialBase] = None, log_file: str = '') -> None:
        self._raw_port = raw_port
        self.log_file = log_file
        self.redirect_disabled = False

    @property
    def serial(self) -> t.Optional[serial.SerialBase]:
        return self._raw_port

    @contextlib.contextmanager
    def disable_redirect_thread(self) -> t.Generator[None, None, None]:
        self.redirect_disabled = True
        yield
        self.redirect_disabled = False


def test_add_mixin_by_type_for_serial_is_idempotent() -> None:
    raw_port = _DummySerial.__new__(_DummySerial)

    SerialPortMixin._add_mixin_by_type(raw_port)
    first_type = type(raw_port)
    assert first_type is SerialExt

    # Calling again should be a no-op and keep the same class.
    SerialPortMixin._add_mixin_by_type(raw_port)
    second_type = type(raw_port)
    assert second_type is first_type


def test_add_mixin_by_type_for_serial_base_is_idempotent() -> None:
    raw_port = _DummySerialBase.__new__(_DummySerialBase)
    original_type = type(raw_port)

    SerialPortMixin._add_mixin_by_type(raw_port)
    first_type = type(raw_port)
    assert first_type is not original_type
    assert issubclass(first_type, SerMixin)

    # Calling again should not create nested dynamic mixin classes.
    SerialPortMixin._add_mixin_by_type(raw_port)
    second_type = type(raw_port)
    assert second_type is first_type
    assert second_type.mro().count(SerMixin) == 1


def test_reopen_remote_url_serial_sets_flow_control_and_opens() -> None:
    port = _ReopenHarness({'port': 'loop://', 'baudrate': 115200, 'timeout': 0.001, 'rtscts': False})
    try:
        port.reopen()
        assert port.serial is not None
        assert isinstance(port.serial, serial.SerialBase)
        assert port.serial.port == 'loop://'
        assert port.serial.is_open is True
        assert port.serial.rts is False
        assert port.serial.dtr is False
        # loop:// should echo data back, proving open/reopen works with real serial_for_url.
        port.serial.write(b'world')
        assert port.serial.read(5) == b'world'
    finally:
        if port.serial:
            port.serial.close()


def test_change_serial_config_applies_baudrate() -> None:
    ser = serial.serial_for_url('loop://', baudrate=115200, timeout=0.05)
    port = SerialPort(ser, name='cfg_port')
    try:
        port.change_serial_config(baudrate=74880)
        assert port.serial is not None
        assert port.serial.baudrate == 74880
    finally:
        port.close()


def test_change_serial_config_raises_when_serial_missing() -> None:
    port = _ChangeConfigHarness(raw_port=None)
    with pytest.raises(OSError, match='serial port not configured'):
        SerialPortMixin.change_serial_config(port, baudrate=115200)  # type: ignore[arg-type]


def test_change_serial_config_disables_redirect_thread_and_logs(tmp_path: Path) -> None:
    ser = serial.serial_for_url('loop://', baudrate=115200, timeout=0.05)
    log_file = str(tmp_path / 'serial.log')
    port = _ChangeConfigHarness(raw_port=ser, log_file=log_file)
    try:
        SerialPortMixin.change_serial_config(port, baudrate=9600)  # type: ignore[arg-type]
        assert ser.baudrate == 9600
        assert port.redirect_disabled is False
        content = Path(log_file).read_text(encoding='utf-8')
        assert 'change serial config' in content
        assert '9600' in content
    finally:
        ser.close()
