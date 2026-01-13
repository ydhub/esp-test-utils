import re
from dataclasses import dataclass

import esptest.common.compat_typing as t

from ..adapter.port.shell_port import ShellPort
from ..all import get_logger
from ..network.mac import format_mac_to_h3c, normalize_mac
from ..network.netif import ip_in_network

logger = get_logger(__name__)

KNOWN_INTERFACE_PREFIXS = [
    'BAG',
    'XGE',
    'HGE',
    'GE',
]
LINK_TYPE_MAP = {
    'A': 'access',
    'T': 'trunk',
    'H': 'hybrid',
}


@dataclass
class SwitchConfig:
    ip: str
    port: int
    login_method: str = 'telnet'
    login_username: str = ''
    login_password: str = ''
    timeout: float = 10

    def __post_init__(self) -> None:
        if self.login_method not in ['ssh', 'telnet']:
            raise ValueError(f'login_method must be ssh or telnet, got {self.login_method}')


@dataclass
class VlanInfo:
    id: int  # 1-4094
    interface_name: str = ''  # Vlan1
    name: str = ''
    type: str = ''  # Static
    status: str = ''  # UP / DOWN
    ip: str = ''  # 10.0.0.1
    mask: str = ''  # 255.255.255.0
    description: str = ''
    # TODO: support more fields
    tagged_ports: str = ''
    untagged_ports: str = ''

    @classmethod
    def parse_interface_brief_line(cls, line: str) -> t.Optional['VlanInfo']:
        """Interface            Link Protocol Primary IP        Description"""
        if not line.startswith('Vlan'):
            return None
        parts = line.split(maxsplit=4)
        if len(parts) not in [4, 5]:
            # description can be empty
            return None
        vlan_id = int(parts[0].replace('Vlan', ''))
        interface_name = parts[0]
        status = parts[1]
        assert status in ['UP', 'DOWN'], f'Invalid status {status}'
        ip = parts[3]
        # mask is not shown in the output
        description = parts[4] if len(parts) == 5 else ''
        return cls(vlan_id, interface_name, '', '', status, ip, '', description)

    def parse_vlan_details(self, line: str) -> None:
        """VLAN ID: 1
        VLAN type: Static
        Route interface: Configured
        IPv4 address: 10.0.0.1
        IPv4 subnet mask: 255.255.255.0
        Description: Server
        Name: VLAN 0001
        """
        match = re.search(r'VLAN ID: (\d+)', line)
        if not match or int(match.group(1)) != self.id:
            raise AssertionError(f'VLAN ID does not match current VLAN ID {self.id}')
        # name
        match = re.search(r'Name:\s*([\S ]+)', line)
        assert match
        self.name = match.group(1).strip()
        # ip and mask
        match = re.search(r'IPv4 address:\s*(\d+\.\d+\.\d+\.\d+)', line)
        assert match and match.group(1) == self.ip, f'IP address does not match current IP address {self.ip}'
        match = re.search(r'IPv4 subnet mask:\s*(\d+\.\d+\.\d+\.\d+)', line)
        assert match
        self.mask = match.group(1).strip()
        # other fields
        match = re.search(r'VLAN type:\s*(\w+)', line)
        if match:
            self.type = match.group(1).strip()
        match = re.search(r'Description:\s*([\S ]+)', line)
        if match:
            self.description = match.group(1).strip()


@dataclass
class PoolInfo:
    name: str
    ip: str = ''  # 10.0.0.1
    mask: str = ''  # 255.255.255.0
    gateway: str = ''  # 10.0.0.1
    dns_list: str = ''  # "8.8.8.8 114.114.114.114"
    # needs vlan info
    vlan_id: int = 0  # which vlan the pool belongs to

    @classmethod
    def parse_pool_info(cls, output: str) -> 'PoolInfo':
        """Pool name: 111
        Network: 10.0.0.0 mask 255.255.254.0
        dns-list 8.8.8.8 114.114.114.114
        expired day 1 hour 0 minute 0 second 0
        gateway-list 10.0.0.1
        static bindings:
            ip-address 10.0.0.10 mask 255.255.254.0
            hardware-address 1122-3344-aabb ethernet
        """
        match = re.search(r'Pool name:\s*(\w+)', output)
        assert match, f'Failed to parse pool name from output: {output}'
        pool_name = match.group(1).strip()
        match = re.search(r'gateway-list\s*(\d+\.\d+\.\d+\.\d+)', output)
        assert match, f'Failed to parse gateway from output: {output}'
        gateway = match.group(1).strip()
        match = re.search(r'Network:\s*(\d+\.\d+\.\d+\.\d+) mask (\d+\.\d+\.\d+\.\d+)', output)
        if match:
            ip = match.group(1).strip()
            mask = match.group(2).strip()
        else:
            logger.warning(
                f'Failed to parse network info from pool {pool_name}, trying parse ip/mask from static bindings'
            )
            ip = gateway.split(' ')[0]
            mask_match = re.search(r'mask (\d+\.\d+\.\d+\.\d+)', output)
            assert mask_match, f'Failed to parse ip/mask from pool: {pool_name}, Please set network config to the pool'
            mask = mask_match.group(1).strip()
        match = re.search(r'dns-list\s*([\d\. ]+)', output)
        assert match
        dns_list = match.group(1).strip()
        return cls(pool_name, ip, mask, gateway, dns_list)


@dataclass
class InterfaceInfo:
    name: str  # XGE1/0/1
    full_name: str = ''  # Ten-GigabitEthernet1/0/1
    description: str = ''
    status: str = ''  # UP / DOWN
    speed: str = ''  # 1000M
    duplex: str = ''  # F(a) / A
    link_mode: str = ''  # bridge
    link_type: str = ''  # access/trunk
    pvid: int = 0  # which vlan the interface belongs to
    permit_vlan: str = ''  # 1, 205 to 206

    @classmethod
    def parse_interface_line(cls, line: str) -> t.Optional['InterfaceInfo']:
        """Interface            Link Speed     Duplex Type PVID Description"""
        if not any(line.startswith(prefix) for prefix in KNOWN_INTERFACE_PREFIXS):
            return None
        parts = line.split(maxsplit=6)
        if len(parts) not in [6, 7]:
            # description can be empty
            return None
        interface_name = parts[0]
        status = parts[1]
        assert status in ['UP', 'DOWN'], f'Invalid status {status} ({line})'
        speed = parts[2]
        # Duplex: (a)/A - auto; H - half; F - full
        duplex = parts[3]
        if parts[4] in ['A', 'T', 'H']:
            # Type: A - access; T - trunk; H - hybrid
            link_type = LINK_TYPE_MAP[parts[4]]
        else:
            link_type = ''
        try:
            pvid = int(parts[5])
        except ValueError:
            pvid = 0
        # mask is not shown in the output
        description = parts[6] if len(parts) == 7 else ''
        return cls(interface_name, '', description, status, speed, duplex, '', link_type, pvid, '')

    def parse_interface_details(self, data: str) -> None:
        """
        interface Ten-GigabitEthernet1/0/1
        description test
        port link-mode bridge
        port link-type trunk
        undo port trunk permit vlan 1
        port trunk permit vlan 111 to 112 2000
        port link-aggregation group 1
        """
        # full name
        match = re.search(r'interface\s+(\S+)', data)
        assert match
        self.full_name = match.group(1).strip()
        # vlan
        match = re.search(r'port trunk permit vlan\s+([\S ]+)', data)
        assert match
        self.permit_vlan = match.group(1).strip()
        # link mode
        match = re.search(r'port link-mode\s+(\w+)', data)
        if match:
            self.link_mode = match.group(1).strip()


@dataclass
class ArpInfo:
    ip: str
    mac: str
    vlan_id: str
    interface: str = ''
    # aging: str = ''  # ignored
    type: str = ''  # D
    # needs pool info
    pool_name: str = ''  # which pool the arp entry belongs to

    @classmethod
    def parse_arp_line(cls, line: str) -> t.Optional['ArpInfo']:
        """IP address      MAC address    VLAN/VSI name Interface                Aging Type"""
        parts = line.split(maxsplit=5)
        if len(parts) != 6 or not re.match(r'\d+\.\d+\.\d+\.\d+', parts[0]):
            return None
        ip = parts[0]
        mac = normalize_mac(parts[1])
        vlan_id = parts[2]
        interface = parts[3]
        # aging = parts[4]  # ignored
        typ = parts[5].strip()
        return cls(ip, mac, vlan_id, interface, typ)


@dataclass
class StaticBindInfo:
    ip: str
    mask: str
    hardware_address: str
    # needs pool info
    pool_name: str = ''  # which pool the arp entry belongs to

    @property
    def mac(self) -> str:
        return normalize_mac(self.hardware_address)


class H3CSwitch:
    def __init__(self, config: SwitchConfig, log_file: str = '') -> None:
        self.config = config
        self.ip = config.ip
        self.port = config.port
        self.login_method = config.login_method
        self.username = config.login_username
        self.password = config.login_password
        self.timeout = config.timeout
        self.log_file = log_file
        self.session: t.Optional[ShellPort] = None
        self.sysname = ''
        self.need_save = False
        # cache
        self._vlan_info_list: t.List[VlanInfo] = []
        self._interface_info_list: t.List[InterfaceInfo] = []
        self._pool_name_list: t.List[str] = []
        self._pool_info_list: t.List[PoolInfo] = []
        self._arp_info_list: t.List[ArpInfo] = []
        self._static_bind_info_list: t.List[StaticBindInfo] = []

    def connect(self) -> None:
        """
        Connect to the switch.
        """
        if self.session:
            # already connected
            try:
                self.system_view()
                return
            except TimeoutError:
                pass

        _switch_name = f'H3C-Switch-{self.ip}-{self.port}'
        # Use TERM=xterm to avoid "'xterm-256color': unknown terminal type.".
        if self.login_method == 'telnet':
            self.session = ShellPort(f'TERM=xterm telnet {self.ip}', name=_switch_name, log_file=self.log_file)
            self.session.timeout = self.timeout
            self.session.expect('Login: ')
            self.session.write_line(self.username)
        else:
            self.session = ShellPort(f'TERM=xterm ssh {self.username}@{self.ip}', log_file=self.log_file)

        self.session.expect('Password:')
        self.session.write_line(self.password)
        match = self.session.expect(re.compile(r'<(\w+)>'))
        self.sysname = match.group(1)
        # Disable pagination
        self.session.write_line('screen-length disable')
        self.session.expect(f'<{self.sysname}>')
        self.session.write_line('system-view')
        self.session.expect(f'[{self.sysname}]')
        logger.info(f'Connected to switch: {self.ip}:{self.port}')

    def disconnect(self) -> None:
        """Disconnect from the switch, and save the configuration if needed."""
        if self.session:
            if self.need_save:
                self.save()
            self.session.close()
            logger.info(f'Disconnected from switch: {self.ip}:{self.port}')
            self.session = None
            self.sysname = ''

    def save(self) -> None:
        """Save the configuration of the switch."""
        if self.session:
            self.session.write_line('save f')
            self.session.expect('successfully.')
            self.session.expect(self.sysname)
            self.need_save = False
            logger.info('Switch configuration saved successfully.')

    def reset_cache(self) -> None:
        """Reset the cache of the switch."""
        self._vlan_info_list = []
        self._interface_info_list = []
        self._pool_name_list = []
        self._pool_info_list = []
        self._arp_info_list = []
        self._static_bind_info_list = []

    def __enter__(self) -> 'H3CSwitch':
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        self.disconnect()

    def execute_command(self, command: str, timeout: float = -1) -> str:
        """Execute a command on the switch and return the result."""
        if timeout == -1:
            timeout = self.timeout
        if self.session:
            # ensure internal buffers are flushed before sending a command
            self.session.flush_data()
            self.session.write_line(command)
            # escape special chars for regex matching
            # limit the length to 20 chars, because H3C echo may insert new line
            _command_escaped = re.escape(command[:20])
            match = self.session.expect(
                re.compile(rf'({_command_escaped}[\s\S]+[\[<]{self.sysname}\S*[\]>])'), timeout=timeout
            )
            # return the captured output between the echoed command and the prompt
            return match.group(1).strip()
        return ''

    def system_view(self) -> bool:
        """Enter system view of the switch."""
        if not self.session:
            return False
        self.session.flush_data()
        self.session.write_line('')
        match = self.session.expect(re.compile(rf'([\[<]{self.sysname}[-\w]*[\]>])'))
        data = match.group(1)
        if data.startswith('<'):
            self.session.write_line('system-view')
            self.session.expect(f'[{self.sysname}]')
            return True
        if data == f'[{self.sysname}]':
            # already in system view
            return True
        assert data.startswith(f'[{self.sysname}')
        self.session.write_line('qu')
        self.session.expect(f'[{self.sysname}]')
        return True

    def get_vlan_info(self) -> t.List[VlanInfo]:
        """Get VLAN (interface) information from the switch."""
        if self._vlan_info_list:
            return self._vlan_info_list
        # show vlan interfaces
        command = 'display interface Vlan-interface brief'
        output = self.execute_command(command)
        self._vlan_info_list = []
        for line in output.splitlines():
            if not line.startswith('Vlan'):
                continue
            new_vlan = VlanInfo.parse_interface_brief_line(line)
            assert new_vlan
            output = self.execute_command(f'display vlan {new_vlan.id}')
            new_vlan.parse_vlan_details(output)
            self._vlan_info_list.append(new_vlan)
        logger.info(f'Get vlan [interface] info: {len(self._vlan_info_list)} vlans')
        return self._vlan_info_list

    def get_pool_name_list(self) -> t.List[str]:
        """Get pool name list from the switch."""
        if self._pool_name_list:
            return self._pool_name_list
        # show pool
        command = 'display dhcp server pool | include name'
        output = self.execute_command(command)
        self._pool_name_list = []
        for match in re.finditer(r'Pool name:\s*(\S+)', output):
            pool_name = match.group(1)
            self._pool_name_list.append(pool_name)
        return self._pool_name_list

    def get_pool_info(self) -> t.List[PoolInfo]:
        """Get pool information from the switch."""
        if self._pool_info_list:
            return self._pool_info_list
        # show pool
        pool_names = self.get_pool_name_list()
        for pool_name in pool_names:
            output = self.execute_command(f'display dhcp server pool {pool_name}')
            new_pool = PoolInfo.parse_pool_info(output)
            assert new_pool
            # try to add vlan_id to the pool
            for vlan in self.get_vlan_info():
                if vlan.ip in new_pool.gateway:
                    new_pool.vlan_id = vlan.id
                    break
            self._pool_info_list.append(new_pool)
        logger.info(f'Get pool list: {len(self._pool_info_list)} pools')
        return self._pool_info_list

    def get_interface_info(self, detail: bool = False) -> t.List[InterfaceInfo]:
        """Get interface information from the switch."""
        if self._interface_info_list:
            return self._interface_info_list
        # show pool
        command = 'display interface brief'
        output = self.execute_command(command)
        self._interface_info_list = []
        for line in output.splitlines():
            new_interface = InterfaceInfo.parse_interface_line(line)
            if new_interface:
                if detail:
                    # add interface vlan info (display this in interface view)
                    self.system_view()
                    self.execute_command(f'interface {new_interface.name}')
                    output = self.execute_command('display this')
                    new_interface.parse_interface_details(output)
                    self.system_view()
                self._interface_info_list.append(new_interface)
        logger.info(f'Get interface list: {len(self._interface_info_list)} interfaces')
        return self._interface_info_list

    def get_arp_info(self) -> t.List[ArpInfo]:
        """Get ARP information from the switch."""
        if self._arp_info_list:
            return self._arp_info_list
        # show pool
        command = 'display arp'
        output = self.execute_command(command)
        self._arp_info_list = []
        for line in output.splitlines():
            new_arp = ArpInfo.parse_arp_line(line)
            if new_arp:
                self._arp_info_list.append(new_arp)
        logger.info(f'Get ARP list: {len(self._arp_info_list)} ARP entries')
        return self._arp_info_list

    def get_static_bind_info(self) -> t.List[StaticBindInfo]:
        """Get static bind information from the switch."""
        if self._static_bind_info_list:
            return self._static_bind_info_list
        self._static_bind_info_list = []
        pattern = re.compile(r'ip-address\s+([\d\.]+)\s+mask\s+([\d\.]+)\s+hardware-address\s+(\S+)\s')
        for pool in self.get_pool_name_list():
            command = f'display dhcp server pool {pool}'
            output = self.execute_command(command)
            for match in pattern.finditer(output):
                ip_address = match.group(1)
                mask = match.group(2)
                hardware_address = match.group(3)
                new_bind = StaticBindInfo(ip_address, mask, hardware_address, pool)
                self._static_bind_info_list.append(new_bind)
        logger.info(f'Get static bind list: {len(self._static_bind_info_list)} static binds')
        return self._static_bind_info_list

    def get_pool_by_ip(self, ip_address: str) -> PoolInfo:
        """Get pool name by IP address."""
        for pool in self.get_pool_info():
            if ip_in_network(ip_address, f'{pool.ip}/{pool.mask}'):
                return pool
        logger.error(f'get_pool_by_ip failed: {ip_address}')
        raise ValueError(f'IP address {ip_address} not found in any pool')

    def get_arp_info_by_ip(self, ip_address: str) -> ArpInfo:
        """Get ARP information by IP address."""
        if self._arp_info_list:
            for arp_info in self._arp_info_list:
                if arp_info.ip == ip_address:
                    return arp_info
        output = self.execute_command(f'display arp {ip_address}')
        for line in output.splitlines():
            if line.startswith(ip_address):
                arp_info = ArpInfo.parse_arp_line(line)  # type: ignore
                if arp_info:
                    return arp_info
        logger.error(f'get_arp_info_by_ip failed: {ip_address}')
        raise ValueError(f'IP address {ip_address} not found in ARP table')

    def add_one_static_bind(  # pylint: disable=too-many-positional-arguments
        self,
        ip_address: str,
        hardware_address: str = '',
        mask: str = '',
        pool_name: str = '',
        remove_existing: bool = False,
    ) -> t.Optional[StaticBindInfo]:
        """Add static bind information to the switch.

        Args:
            ip_address: IP address to bind.
            hardware_address: Hardware address to bind.
            mask: Subnet mask.
            pool_name: Pool name.
            remove_existing: Remove existing bind information for the IP address.
        """
        if pool_name:
            if not mask:
                raise ValueError('Mask is required when pool_name is specified')
            if pool_name not in self.get_pool_name_list():
                raise ValueError(f'Pool {pool_name} not found on this switch')
        else:
            pool = self.get_pool_by_ip(ip_address)
            pool_name = pool.name
            mask = pool.mask
        if not hardware_address:
            hardware_address = self.get_arp_info_by_ip(ip_address).mac
        hardware_address = format_mac_to_h3c(hardware_address)
        new_bind_info = None
        self.system_view()
        command = f'dhcp server ip-pool {pool_name}'
        self.execute_command(command)
        try:
            if remove_existing:
                logger.debug(f'Try to remove existing bind info for {ip_address} in pool: {pool_name}.')
                command = f'undo static-bind ip-address {ip_address}'
                self.execute_command(command)
            logger.info(f'Bind static dhcp {ip_address} {mask} {hardware_address} to pool {pool_name}.')
            command = f'static-bind ip-address {ip_address} mask {mask} hardware-address {hardware_address}'
            output = self.execute_command(command)
            if 'The IP address has already been bound' in output:
                raise ValueError(f'IP address {ip_address} has already been bound, pool:{pool_name}')
            new_bind_info = StaticBindInfo(ip_address, mask, hardware_address, pool_name)
        except (TimeoutError, ValueError) as e:
            logger.error(f'Failed to bind {ip_address} {mask} {hardware_address}, pool:{pool_name}, error:{str(e)}')
            raise

        if new_bind_info:
            self.need_save = True
            if self._static_bind_info_list:
                self._static_bind_info_list.append(new_bind_info)
        self.system_view()  # return to system view
        return new_bind_info

    def remove_one_static_bind(  # pylint: disable=too-many-positional-arguments
        self,
        ip_address: str,
        pool_name: str = '',
    ) -> t.Optional[StaticBindInfo]:
        """Remove static bind information from the switch.

        Args:
            ip_address: IP address to unbind.
            pool_name: Pool name.
        """
        if pool_name:
            if pool_name not in self.get_pool_name_list():
                raise ValueError(f'Pool {pool_name} not found on this switch')
        else:
            pool = self.get_pool_by_ip(ip_address)
            pool_name = pool.name
            mask = pool.mask
        self.system_view()
        command = f'dhcp server ip-pool {pool_name}'
        self.execute_command(command)
        try:
            logger.info(f'removing existing bind info for {ip_address} in pool: {pool_name}.')
            command = f'undo static-bind ip-address {ip_address}'
            self.execute_command(command)
            output = self.execute_command(command)
            if 'The IP address has already been bound' in output:
                raise ValueError(f'IP address {ip_address} has already been bound, pool:{pool_name}')
            new_bind_info = StaticBindInfo(ip_address, mask, hardware_address, pool_name)
        except (TimeoutError, ValueError) as e:
            logger.error(f'Failed to bind {ip_address} {mask} {hardware_address}, pool:{pool_name}, error:{str(e)}')
            raise

        if new_bind_info:
            self.need_save = True
            if self._static_bind_info_list:
                self._static_bind_info_list.append(new_bind_info)
        self.system_view()  # return to system view
        return new_bind_info

    def remove_one_static_bind(  # pylint: disable=too-many-positional-arguments
        self,
        ip_address: str,
        pool_name: str = '',
    ) -> t.Optional[StaticBindInfo]:
        """Remove static bind information from the switch.

        Args:
            ip_address: IP address to unbind.
            pool_name: Pool name.
        """
        if pool_name:
            if pool_name not in self.get_pool_name_list():
                raise ValueError(f'Pool {pool_name} not found on this switch')
        else:
            pool = self.get_pool_by_ip(ip_address)
            pool_name: Pool name.
            remove_existing: Remove existing bind information for the IP address.
        """
        if pool_name:
            if not mask:
                raise ValueError('Mask is required when pool_name is specified')
            if pool_name not in self.get_pool_name_list():
                raise ValueError(f'Pool {pool_name} not found on this switch')
        else:
            pool = self.get_pool_by_ip(ip_address)
            pool_name = pool.name
            mask = pool.mask
        if not hardware_address:
            hardware_address = self.get_arp_info_by_ip(ip_address).mac
        hardware_address = format_mac_to_h3c(hardware_address)
        new_bind_info = None
        self.system_view()
        command = f'dhcp server ip-pool {pool_name}'
        self.execute_command(command)
        try:
            if remove_existing:
                logger.debug(f'Try to remove existing bind info for {ip_address} in pool: {pool_name}.')
                command = f'undo static-bind ip-address {ip_address}'
                self.execute_command(command)
            logger.info(f'Bind static dhcp {ip_address} {mask} {hardware_address} to pool {pool_name}.')
            command = f'static-bind ip-address {ip_address} mask {mask} hardware-address {hardware_address}'
            output = self.execute_command(command)
            if 'The IP address has already been bound' in output:
                raise ValueError(f'IP address {ip_address} has already been bound, pool:{pool_name}')
            new_bind_info = StaticBindInfo(ip_address, mask, hardware_address, pool_name)
        except (TimeoutError, ValueError) as e:
            logger.error(f'Failed to bind {ip_address} {mask} {hardware_address}, pool:{pool_name}, error:{str(e)}')
            raise

        if new_bind_info:
            self.need_save = True
            if self._static_bind_info_list:
                self._static_bind_info_list.append(new_bind_info)
        self.system_view()  # return to system view
        return new_bind_info
