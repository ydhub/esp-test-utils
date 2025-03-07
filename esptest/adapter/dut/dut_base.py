from typing import Any, AnyStr, Dict, Union

from ...network.mac import mac_offset
from ..base_port import BasePort


class DutMacMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._device_mac: str = '00:00:00:00:00:00'
        self._sta_mac: str = ''
        self._ap_mac: str = ''
        self._bt_mac: str = ''
        self._eth_mac: str = ''

    @property
    def mac(self) -> str:
        return self._device_mac

    @property
    def device_mac(self) -> str:
        return self._device_mac

    @device_mac.setter
    def device_mac(self, value: str) -> None:
        self._device_mac = value

    @property
    def sta_mac(self) -> str:
        return self._sta_mac or self._device_mac

    @sta_mac.setter
    def sta_mac(self, value: str) -> None:
        self._sta_mac = value

    @property
    def ap_mac(self) -> str:
        return self._ap_mac or mac_offset(self._device_mac, 1)

    @ap_mac.setter
    def ap_mac(self, value: str) -> None:
        self._ap_mac = value

    @property
    def bt_mac(self) -> str:
        return self._bt_mac or mac_offset(self._device_mac, 2)

    @bt_mac.setter
    def bt_mac(self, value: str) -> None:
        self._bt_mac = value

    @property
    def eth_mac(self) -> str:
        # do not generate eth mac from device mac
        return self._eth_mac  # or mac_offset(self._device_mac, 3)

    @eth_mac.setter
    def eth_mac(self, value: str) -> None:
        self._eth_mac = value


class DutPort(DutMacMixin, BasePort):
    """Add dut related methods to Port"""

    def __init__(self, dut: Any, name: str, log_file: str = '') -> None:
        super().__init__(dut, name, log_file)

    def write_line(self, data: AnyStr, end: str = '\r\n') -> None:
        """Use \\r\\n as default ending"""
        return super().write_line(data, end)

    def stop_receive_thread(self) -> None:
        raise NotImplementedError()

    def start_receive_thread(self) -> None:
        self.start_pexpect_proc()

    # Attributes needed by bin path
    @property
    def bin_path(self) -> str:
        raise NotImplementedError()

    @property
    def sdkconfig(self) -> Dict[str, Any]:
        raise NotImplementedError()

    @property
    def target(self) -> str:
        raise NotImplementedError()

    @property
    def partition_table(self) -> Dict[str, Any]:
        raise NotImplementedError()

    # Serial Specific
    def reconfigure(self) -> bool:
        raise NotImplementedError()

    def hard_reset(self) -> None:
        raise NotImplementedError()

    # EspTool Specific
    def flash(self, bin_path: str = '') -> None:
        raise NotImplementedError()

    def flash_partition(self, part: Union[int, str], bin_path: str = '') -> None:
        raise NotImplementedError()

    def flash_nvs(self, bin_path: str = '') -> None:
        raise NotImplementedError()

    def dump_flash(self, part: Union[int, str], bin_path: str, size: int = 0) -> None:
        raise NotImplementedError()

    # More extra methods may be implemented
