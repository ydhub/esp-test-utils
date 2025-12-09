import json
import os
from pathlib import Path

import pytest

from esptest.devices.switch import ArpInfo, H3CSwitch, InterfaceInfo, PoolInfo, StaticBindInfo, SwitchConfig, VlanInfo

H3C_SWITCH_CONFIG = os.environ.get('H3C_SWITCH_CONFIG', '')


def test_vlan_info_parser() -> None:
    """Test VLAN info parser."""
    line_data = 'Vlan111              DOWN DOWN     10.0.0.1      test 111'
    vlan_info = VlanInfo.parse_interface_brief_line(line_data)
    assert vlan_info
    assert vlan_info.id == 111
    # assert vlan_info.name == 'Vlan111'
    assert vlan_info.status == 'DOWN'
    assert vlan_info.description == 'test 111'
    assert vlan_info.ip == '10.0.0.1'
    vlan_data = """
        VLAN ID: 111
        VLAN type: Static
        Route interface: Configured
        IPv4 address: 10.0.0.1
        IPv4 subnet mask: 255.255.254.0
        Description: test 111
        Name: VLAN 0111
        Tagged ports:
            Ten-GigabitEthernet1/0/3(U)
        Untagged ports:
            None
    """
    vlan_info.parse_vlan_details(vlan_data)
    assert vlan_info.status == 'DOWN'
    assert vlan_info.name == 'VLAN 0111'
    assert vlan_info.ip == '10.0.0.1'
    assert vlan_info.mask == '255.255.254.0'
    assert vlan_info.type == 'Static'


def test_pool_info_parser() -> None:
    """Test Pool info parser."""
    pool_data = """
        Pool name: 111
        Network: 10.0.0.0 mask 255.255.254.0
        dns-list 8.8.8.8 114.114.114.114
        expired day 3 hour 0 minute 0 second 0
        gateway-list 10.0.0.1
        static bindings:
            ip-address 10.0.0.254 mask 255.255.254.0
            hardware-address 0000-0000-0000 ethernet
    """
    pool_info = PoolInfo.parse_pool_info(pool_data)
    assert pool_info
    assert pool_info.ip == '10.0.0.0'
    assert pool_info.mask == '255.255.254.0'
    assert pool_info.dns_list == '8.8.8.8 114.114.114.114'
    assert pool_info.gateway == '10.0.0.1'
    # remove network config, parse mask from gateway and static bind
    pool_data = pool_data.replace('Network: 10.0.0.0 mask 255.255.254.0', '')
    pool_info = PoolInfo.parse_pool_info(pool_data)
    assert pool_info
    assert pool_info.ip == '10.0.0.1'
    assert pool_info.mask == '255.255.254.0'
    assert pool_info.dns_list == '8.8.8.8 114.114.114.114'
    assert pool_info.gateway == '10.0.0.1'


def test_interface_info_parser() -> None:
    """Test interface info parser."""
    line_data = 'XGE1/0/1            UP   10G     F(a)   A    111  Ten-GigabitEthernet1/0/1 (access) (vlan111)'
    interface_info = InterfaceInfo.parse_interface_line(line_data)
    assert interface_info
    assert interface_info.name == 'XGE1/0/1'
    assert interface_info.status == 'UP'
    assert interface_info.speed == '10G'
    assert interface_info.duplex == 'F(a)'
    assert interface_info.link_type == 'access'
    assert interface_info.pvid == 111
    assert interface_info.description == 'Ten-GigabitEthernet1/0/1 (access) (vlan111)'
    line_data = 'HGE1/0/35            UP   auto      F(a)   --   --   '
    interface_info = InterfaceInfo.parse_interface_line(line_data)
    assert interface_info
    assert interface_info.name == 'HGE1/0/35'
    assert interface_info.status == 'UP'
    assert interface_info.speed == 'auto'
    assert interface_info.duplex == 'F(a)'
    assert interface_info.link_type == ''
    assert interface_info.pvid == 0
    assert interface_info.description == ''


def test_arp_info_parser() -> None:
    """Test ARP info parser."""
    line_data = 'IP address      MAC address    VLAN/VSI name Interface                Aging Type'
    arp_info = ArpInfo.parse_arp_line(line_data)
    assert not arp_info
    line_data = '10.0.0.2     1122-3344-aabb 111           BAGG1                    889   D  '
    arp_info = ArpInfo.parse_arp_line(line_data)
    assert arp_info
    assert arp_info.ip == '10.0.0.2'
    assert arp_info.mac == '11:22:33:44:AA:BB'
    assert arp_info.vlan_id == '111'
    assert arp_info.interface == 'BAGG1'
    # assert arp_info.aging == '889'
    assert arp_info.type == 'D'


def test_static_bind_info_mac() -> None:
    bind_info = StaticBindInfo('10.0.0.254', '255.255.254.0', '0000-0000-aabb')
    assert bind_info.mac == '00:00:00:00:AA:BB'


@pytest.mark.skipif(not H3C_SWITCH_CONFIG, reason='H3C_SWITCH_CONFIG is not set')
def test_h3c_switch_login_out(tmp_path: Path) -> None:
    """Test login and logout of H3C switch."""
    config = SwitchConfig(**json.loads(H3C_SWITCH_CONFIG))
    switch = H3CSwitch(config, log_file=str(tmp_path / 'h3c_switch.log'))
    switch.connect()
    switch.disconnect()


@pytest.mark.skipif(not H3C_SWITCH_CONFIG, reason='H3C_SWITCH_CONFIG is not set')
def test_h3c_switch_execute_command() -> None:
    """Test execute command of H3C switch."""
    config = SwitchConfig(**json.loads(H3C_SWITCH_CONFIG))
    with H3CSwitch(config) as h3c:
        result = h3c.execute_command('display version')
        assert 'H3C' in result


@pytest.mark.skipif(not H3C_SWITCH_CONFIG, reason='H3C_SWITCH_CONFIG is not set')
def test_h3c_system_view() -> None:
    """Test system view of H3C switch."""
    config = SwitchConfig(**json.loads(H3C_SWITCH_CONFIG))
    with H3CSwitch(config) as h3c:
        # default system view, quit to user view
        h3c.execute_command('qu')
        # enter system view
        h3c.system_view()
        # check system view
        assert h3c.session
        h3c.session.flush_data()
        h3c.session.write_line('')
        h3c.session.expect(f'[{h3c.sysname}]')
        # enter system view
        h3c.system_view()
        # check system view
        h3c.session.write_line('')
        h3c.session.expect(f'[{h3c.sysname}]')
        # Enter vlan 1
        h3c.execute_command('vlan 1')
        # check vlan 1
        h3c.session.write_line('')
        h3c.session.expect('-vlan1]')
        h3c.system_view()
        # check system view
        h3c.session.write_line('')
        h3c.session.expect(f'[{h3c.sysname}]')


@pytest.mark.skipif(not H3C_SWITCH_CONFIG, reason='H3C_SWITCH_CONFIG is not set')
def test_h3c_get_methods() -> None:
    """Test system view of H3C switch."""
    config = SwitchConfig(**json.loads(H3C_SWITCH_CONFIG))
    with H3CSwitch(config) as h3c:
        # get vlan list
        vlan_list = h3c.get_vlan_info()
        assert vlan_list
        vlan_0 = vlan_list[0]
        assert vlan_0.id != 0
        assert vlan_0.ip != ''
        assert vlan_0.mask != ''
        # get pool list
        pool_list = h3c.get_pool_info()
        assert pool_list
        pool_0 = pool_list[0]
        assert pool_0.name != ''
        assert pool_0.ip != ''
        assert pool_0.mask != ''
        assert pool_0.gateway != ''
        assert pool_0.dns_list != ''
        assert pool_0.vlan_id != 0
        # get interface list
        interface_list = h3c.get_interface_info()
        assert interface_list
        interface_names = [interface_info.name for interface_info in interface_list]
        assert '1/0/1' in ' '.join(interface_names)
        # get arp list
        arp_list = h3c.get_arp_info()
        assert arp_list
        # get static bind list
        static_bind_list = h3c.get_static_bind_info()
        assert static_bind_list


@pytest.mark.skipif(not H3C_SWITCH_CONFIG, reason='H3C_SWITCH_CONFIG is not set')
def test_h3c_add_static_bind() -> None:
    """Test system view of H3C switch."""
    test_bind_ip = os.getenv('H3C_SWITCH_TEST_BIND_IP', '192.168.254.2')
    config = SwitchConfig(**json.loads(H3C_SWITCH_CONFIG))
    with H3CSwitch(config) as h3c:
        res = h3c.add_one_static_bind(test_bind_ip, '11:22:33:44:AA:BB', mask='255.255.255.0')
        assert res
        bind_list = h3c.get_static_bind_info()
        assert bind_list
        assert test_bind_ip in [bind_info.ip for bind_info in bind_list]
        bind_info = [bind_info for bind_info in bind_list if bind_info.ip == test_bind_ip][0]
        assert bind_info.mac == '11:22:33:44:AA:BB'


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
