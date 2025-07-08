import esptool
import serial

import esptest.common.compat_typing as t

from ...devices.serial_tools import compute_serial_port
from ..port.base_port import BasePort, RawPort
from ..port.serial_port import SerialExt, SerialPort
from .dut_base import DutBase, DutConfig
from .esp_mixin import EspMixin, EspSerial
from .mac_mixin import MacMixin


class _DefaultMixins(MacMixin, EspMixin):
    pass


class EspDut(_DefaultMixins, DutBase):
    def __init__(self, *, dut_config: DutConfig, **kwargs: t.Any) -> None:
        # __enter__ and __exit__
        self._close_redirect_thread_when_exit = True
        self._close_base_port_when_exit = True
        self._close_raw_port_when_exit = True
        self._close_download_port_when_exit = False
        super().__init__(dut_config=dut_config, **kwargs)

    def _post_init(self) -> None:
        self._base_port_proxy = self._create_base_port()
        super()._post_init()

    def _create_base_port(self) -> t.Optional[BasePort]:
        _config = self._dut_config
        _base_port = None
        if _config.opened_port:
            if isinstance(_config.opened_port, BasePort):
                _base_port = _config.opened_port
                self._close_base_port_when_exit = False
                self._close_raw_port_when_exit = False
                return _base_port
            if isinstance(_config.opened_port, RawPort):
                _base_port = BasePort(_config.opened_port, name=_config.name, log_file=_config.log_file)
                self._close_raw_port_when_exit = False
                return _base_port
            raise TypeError(f'Can not create dut from {type(_config.opened_port)}')

        assert _config.device, 'No device provided in DutConfig'
        _device = compute_serial_port(_config.device, strict=True)
        if _config.support_esptool:
            # create esp port
            _esp = self._esptool_open_port(_device, _config.baudrate, chip=_config.esptool_chip)
            _esp._port.timeout = _config.serial_read_timeout  # pylint: disable=protected-access
            _esp.hard_reset()
            self._raw_port = _esp
            return BasePort(EspSerial(self._raw_port), name=_config.name, log_file=_config.log_file)
        # create basic serial port
        self._raw_port = SerialExt(port=_device, baudrate=_config.baudrate, **(_config.serial_configs or {}))
        return SerialPort(self._raw_port, name=_config.name, log_file=_config.log_file)

    def close(self) -> None:
        if self._close_base_port_when_exit:
            assert self._base_port_proxy
            self._base_port_proxy.close()
        if self._close_raw_port_when_exit:
            if isinstance(self.raw_port, esptool.ESPLoader):
                self.raw_port._port.close()  # pylint: disable=protected-access
            elif isinstance(self.raw_port, serial.Serial):
                self.raw_port.close()
            # TODO: other types
        super().close()
