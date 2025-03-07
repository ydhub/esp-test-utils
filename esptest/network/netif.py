import ipaddress
import socket
from socket import AddressFamily  # type hint
from typing import Iterator, List

import psutil

from ..logger import get_logger

# netifaces needs a new maintaine
# https://github.com/al45tair/netifaces/issues/78
# use psutil instead


logger = get_logger('network')


def get_interfaces() -> List[str]:
    """Get all network interfaces names.

    Returns:
        List[str]: interface names
    """
    return list(psutil.net_if_addrs().keys())


def get_all_ips_from_interface(interface: str, family: AddressFamily = socket.AF_INET, prefix: str = '') -> List[str]:
    """Get the IP address from network interface name.

    Args:
        interface (str): specify network interface name
        family (str, optional): address family. Defaults to AF_INET.
        prefix (str, optional): filter ip address by prefix. Defaults to ''.

    Raises:
        ValueError: Can not get IP address

    Returns:
        List[str]: IP addresses from the interface
    """
    addr_list = []
    for if_name, addrs in psutil.net_if_addrs().items():
        if interface and if_name != interface:
            continue
        for addr in addrs:
            if addr.family != family:
                continue
            _ip = ipaddress.ip_address(addr.address)
            if prefix and not addr.address.startswith(prefix):
                continue
            # Sort all available IP addresses.
            # Put private ip4 or link-local ipv6 to the last
            if _ip.is_loopback:
                # Do not ignore loopback addresses
                addr_list.append(addr.address)
            elif _ip.is_link_local:
                # '169.254.x.x', 'fe80::'
                addr_list.append(addr.address)
            else:
                addr_list.insert(0, addr.address)
    if not addr_list:
        raise ValueError(f'Can not get IP address from interface {interface}')
    return addr_list


def get_ip4_from_interface(interface: str = '') -> str:
    """Get the IPv4 address from network interface name.

    Args:
        interface (str, optional): specify network interface name

    Returns:
        str: The most preferred IP address
    """
    return get_all_ips_from_interface(interface, socket.AF_INET)[0]


def get_ip6_from_interface(interface: str = '', prefix: str = '') -> str:
    """Get the IPv6 address from network interface name.

    Args:
        interface (str, optional): specify network interface name
        prefix (str, optional): filter ip address by prefix. Defaults to ''.

    Returns:
        str: The most preferred IPv6 address
    """
    return get_all_ips_from_interface(interface, socket.AF_INET6, prefix=prefix)[0]


def get_local_ip4(to_addr: str = '') -> str:
    """Get the local IP (v4) that most likely to be able to connect to a remote IP or the Internet.

    Depends on the routing table settings of this machine,
    usually returns the highest priority IP in the routing table.

    Args:
        to_addr (str, optional): Try to get an IP that connect to this remote. Defaults to '8.8.8.8'(Internet).

    Returns:
        str: local IP address
    """
    if not to_addr:
        to_addr = '8.8.8.8'
    s1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s1.connect((to_addr, 80))
    local_ip = s1.getsockname()[0]
    s1.close()
    assert isinstance(local_ip, str)
    logger.debug(f'Using host ip: {local_ip}')
    return local_ip


def ip_in_network(ip: str, network: str) -> bool:
    """Check the IP (v4/v6) address is in the network with given mask.
    Using ipaddress module: https://docs.python.org/3/library/ipaddress.html#module-ipaddress

    Args:
        ip (str): IP address, eg: 192.168.1.2
        subnet (str): network, eg: 192.168.1.0/24 or 192.168.1.0/255.255.255.0

    Returns:
        bool: True if the IP address is in the network
    """
    return ipaddress.ip_address(ip) in ipaddress.ip_network(network, strict=False)


def guess_local_ip6(
    to_addr: str,
    interface: str = '',
) -> Iterator[str]:
    """Guess ipv6 address by given remote ipv6.

    Args:
        to_addr (str): target ip6 address that you want to establish a connection.
        interface (str, optional): specify local net interface. Defaults to ''.

    Yields:
        Iterator[str]: possible IP addresses (eg: fe80::2%eth0) that may connect to the given to_addr.
    """
    target = ipaddress.ip_address(to_addr)

    for if_name, addrs in psutil.net_if_addrs().items():
        if interface and if_name != interface:
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET6:
                continue
            _ip = ipaddress.ip_address(addr.address)
            assert addr.netmask
            _mask_len = bin(int(ipaddress.ip_address(addr.netmask))).count('1')
            _net = ipaddress.ip_network(f'{addr.address}/{_mask_len}', strict=False)
            if target in _net:
                yield addr.address
            # If target is global address, do not check
            if target.is_global and _ip.is_global:
                yield addr.address


def get_mac_by_interface(interface: str) -> str:
    """Get hardware mac address from network interface name.

    Args:
        interface (str): net interface name

    Returns:
        str: mac address
    """
    if_addrs = psutil.net_if_addrs()
    for addr in if_addrs[interface]:
        if addr.family == socket.AF_PACKET:
            assert isinstance(addr.address, str)
            return addr.address
    raise ValueError(f'Failed to get addr info from {interface}')


def get_interface_by_mac(mac_addr: str) -> str:
    """Get network interface name by given mac address.

    Args:
        mac_addr (str): hardware mac address.

    Returns:
        str: network interface name
    """
    for interface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family != socket.AF_PACKET:
                continue
            if addr.address == mac_addr:
                assert isinstance(interface, str)
                return interface
    raise ValueError(f'Failed to get interface with mac {mac_addr}')
