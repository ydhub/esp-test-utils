from typing import Any

from ...network.mac import mac_offset


class MacMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._mac: str = '00:00:00:00:00:00:00:00'
        self._base_mac: str = '00:00:00:00:00:00'
        self._sta_mac: str = ''
        self._ap_mac: str = ''
        self._bt_mac: str = ''
        self._eth_mac: str = ''
        self._i154_mac: str = ''
        super().__init__(*args, **kwargs)

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def base_mac(self) -> str:
        return self._base_mac

    @base_mac.setter
    def base_mac(self, value: str) -> None:
        self._base_mac = value

    @property
    def sta_mac(self) -> str:
        return self._sta_mac or self._base_mac

    @sta_mac.setter
    def sta_mac(self, value: str) -> None:
        self._sta_mac = value

    @property
    def ap_mac(self) -> str:
        return self._ap_mac or mac_offset(self._base_mac, 1)

    @ap_mac.setter
    def ap_mac(self, value: str) -> None:
        self._ap_mac = value

    @property
    def bt_mac(self) -> str:
        return self._bt_mac or mac_offset(self._base_mac, 2)

    @bt_mac.setter
    def bt_mac(self, value: str) -> None:
        self._bt_mac = value

    @property
    def eth_mac(self) -> str:
        # do not generate eth mac from device mac
        return self._eth_mac  # or mac_offset(self._base_mac, 3)

    @eth_mac.setter
    def eth_mac(self, value: str) -> None:
        self._eth_mac = value

    @property
    def i154_mac(self) -> str:
        return self._i154_mac

    @i154_mac.setter
    def i154_mac(self, value: str) -> None:
        self._i154_mac = value
