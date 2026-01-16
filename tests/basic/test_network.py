import socket
import sys
from typing import TYPE_CHECKING
from unittest import mock

import psutil
import pytest

# final exported symbol
if TYPE_CHECKING:
    from typing import NamedTuple

    class snicaddr(NamedTuple):
        family: int
        address: str
        netmask: str | None
        broadcast: str | None
        ptp: str | None
else:
    try:
        from psutil._common import snicaddr  # old versions
    except ImportError:
        try:
            from psutil._ntuples import snicaddr  # newer versions
        except ImportError:
            from typing import NamedTuple

            class snicaddr(NamedTuple):
                family: int
                address: str
                netmask: str | None
                broadcast: str | None
                ptp: str | None


from esptest.network import netif
from esptest.network.mac import mac_offset
from esptest.network.nic import Nic

if sys.platform != 'win32':
    AF_MAC_FAMILY = socket.AF_PACKET
    IF1_MAC_ADDR = '11:22:33:44:55:66'
else:
    AF_MAC_FAMILY = psutil.AF_LINK
    IF1_MAC_ADDR = '11-22-33-44-55-66'


MOCK_NETIF_ADDRS = {
    'lo': [
        snicaddr(socket.AF_INET, '127.0.0.1', '255.0.0.0', None, None),
        snicaddr(socket.AF_INET6, '::1', 'ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff', None, None),
        snicaddr(AF_MAC_FAMILY, '00:00:00:00:00:00', None, None, None),
    ],
    'if1': [
        snicaddr(socket.AF_INET, '10.0.0.2', '255.255.255.0', None, None),
        snicaddr(socket.AF_INET6, r'fe80::2%if1', 'ffff:ffff:ffff:ffff::', None, None),
        snicaddr(AF_MAC_FAMILY, IF1_MAC_ADDR, None, None, None),
    ],
}


def test_psutils_net_if_addrs() -> None:
    if_addrs = psutil.net_if_addrs()
    assert isinstance(if_addrs, dict)
    assert if_addrs
    addrs = list(if_addrs.values())[0]
    assert isinstance(addrs, list)
    assert addrs
    assert isinstance(addrs[0], snicaddr)


@mock.patch('psutil.net_if_addrs')
def test_get_local_ip_by_interface(patch_psutil_addrs: mock.Mock) -> None:
    patch_psutil_addrs.return_value = MOCK_NETIF_ADDRS
    ip = netif.get_ip4_from_interface('lo')
    assert ip == '127.0.0.1'
    ip = netif.get_ip6_from_interface('lo')
    assert ip == '::1'
    assert patch_psutil_addrs.call_count > 0


@mock.patch('psutil.net_if_addrs')
def test_guess_ipv6(patch_psutil_addrs: mock.Mock) -> None:
    patch_psutil_addrs.return_value = MOCK_NETIF_ADDRS
    iter_ip = netif.guess_local_ip6('fe80::1')
    ip = next(iter_ip)
    assert ip == r'fe80::2%if1'


@mock.patch('psutil.net_if_addrs')
def test_netif_vs_mac(patch_psutil_addrs: mock.Mock) -> None:
    patch_psutil_addrs.return_value = MOCK_NETIF_ADDRS
    interface = netif.get_interface_by_mac('11:22:33:44:55:66')
    assert interface == 'if1'
    mac = netif.get_mac_by_interface('if1')
    assert mac == '11:22:33:44:55:66'


def test_mac_offset() -> None:
    mac = '00:01:ff:ff:ff:fe'
    assert mac_offset(mac, 1) == '00:01:ff:ff:ff:ff'
    assert mac_offset(mac, 2) == '00:02:00:00:00:00'
    assert mac_offset(mac, -1) == '00:01:ff:ff:ff:fd'


def test_nic_lo_init() -> None:
    lo = Nic('lo')
    assert lo.iface == 'lo'


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
