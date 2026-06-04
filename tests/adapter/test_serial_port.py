import serial

import esptest.common.compat_typing as t
from esptest.adapter.port.serial_port import SerialExt, SerialPortMixin, SerMixin


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
