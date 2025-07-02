import esptest.common.compat_typing as t

from ...devices.serial_tools import compute_serial_port
from ...utility.parse_bin_path import get_baud_from_bin_path
from ..port.base_port import BasePort, RawPort
from ..port.serial_port import SerialExt, SerialPort
from .dut_base import DutBase, DutConfig
from .esp_mixin import EspMixin
from .mac_mixin import MacMixin


class DefaultMixins(MacMixin, EspMixin):
    pass


class EspDut(DefaultMixins, DutBase):
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
                _base_port = BasePort(_config.opened_port, name='_BASE')
                self._close_raw_port_when_exit = False
                return _base_port
            raise TypeError(f'Can not create dut from {type(_config.opened_port)}')
        # create serial port
        assert _config.device, 'No device provided in DutConfig'
        _device = compute_serial_port(_config.device, strict=True)
        _baudrate = _config.baudrate or get_baud_from_bin_path(_config.bin_path) or 115200
        self._close_raw_port_when_exit = True
        self._raw_port = SerialExt(port=_device, baudrate=_baudrate, **(_config.serial_configs or {}))
        return SerialPort(self._raw_port, name=_config.name)
