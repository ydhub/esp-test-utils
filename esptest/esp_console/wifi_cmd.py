import re
import time
import warnings
from dataclasses import dataclass
from typing import Optional

from ..adapter.dut.dut_base import DutPort
from ..common import to_bytes
from ..common import to_str
from ..logger import get_logger

logger = get_logger('esp_console')


@dataclass
class ConnectedInfo:
    ssid: str
    bssid: str = ''
    channel: int = 0
    bandwidth: str = ''
    aid: int = -1
    security: str = ''
    phy: str = ''
    rssi: int = -128
    ip4: str = ''
    ip4_mask: str = ''
    ip4_gw: str = ''
    # There might be multiple ipv6 addresses.
    # please use ip6_[type] rather than ip6 if you have multiple ipv6 addresses
    ip6: str = ''
    ip6_global: str = ''
    ip6_link_local: str = ''
    ip6_site_local: str = ''

    def __str__(self) -> str:
        s = 'WiFi Connected Info: ' f'ssid: {self.ssid}, ' f'bssid: {self.bssid}, ' f'channel: {self.channel}, '
        if self.aid != -1:
            s += f'aid: {self.aid}, '
        if self.security:
            s += f'security: {self.security}, '
        if self.phy:
            s += f'phy: {self.phy}, '
        if self.rssi:
            s += f'rssi: {self.rssi}, '
        if self.ip4:
            s += f'ip4: {self.ip4}, ip4_mask: {self.ip4_mask}, ip4_gw: {self.ip4_gw} '
        # TODO: ipv6
        return s


class WifiCmd:
    """For esp-console based wifi-cmd: https://components.espressif.com/components/esp-qa/wifi-cmd

    Supported wifi-cmd Versions: v0.1.x

    Basic example:
        ```
        from esptest import dut_wrapper
        from esptest.esp_console import WifiCmd
        ...
        with dut_wrapper(serial) as sta_dut:
            connected_info = WifiCmd.connect_wifi(sta_dut, ssid, password)
        sta_ip = connected_info.ip
        ```
    """

    # supported version:
    # 'v1.0'
    # 'v0.1'
    # 'v0.0'  # deprecated, inside IDF example common components
    VERSION = 'v0.1'

    # idf logs, not managed by wifi-cmd
    IDF_WIFI_CONNECTED_PATTERN = re.compile(r'(connected with .+)\n')
    IDF_WIFI_CONNECTED_AP_INFO_PATTERN = re.compile(
        r'wifi:.*security:\s*([^,]+), phy:\s*([\w-]+),\s*rssi:\s*([-\d]+)[^\d]'
    )
    IDF_GOT_IP4_PATTERN = re.compile(r'sta ip: ([\.\d]+), mask: ([\.\d]+), gw: ([\.\d]+)[^\.\d]')
    # wifi connected
    WIFI_CONNECTED_PATTERN = re.compile('WIFI_EVENT_STA_CONNECTED')
    GOT_IP4_PATTERN = re.compile(r'IPv4 address: ([\.\d]+)[^\.\d]')

    @classmethod
    def detect_version(
        cls,
        dut: Optional[DutPort] = None,
        help_text: str = '',
    ) -> str:
        """Detect and update wifi-cmd version from the help log.

        Args:
            dut (DutPort, optional): dut object, used to get help text.
            help_text (str, optional): use given help text rather than getting from dut.

        Returns:
            str: wifi-cmd version, eg: 1.0
        """
        assert dut or help_text, 'One of dut or help_text must be provided!'
        if not help_text:
            assert dut
            dut.write(to_bytes('help\r\n'))
            time.sleep(2)
            match = dut.expect(re.compile('.*', re.DOTALL), timeout=0)
            assert match
            help_text = to_str(match.group(0))

        match_scan = re.search(r'\nscan\s+', help_text)
        match_sta_scan = re.search(r'\nsta_scan\s+', help_text)

        version = cls.VERSION
        if not match_sta_scan:
            assert match_scan, 'Not supported version, neither "scan" nor "sta_scan" were supported.'
            # found "scan", didn't find "sta_scan"1
            warnings.warn(
                'Found deprecated wifi-cmd version (v0.0), please update it as soon as possible!', DeprecationWarning
            )
            version = 'v0.0'
        elif match_scan:
            # found both "scan" and "sta_scan" command
            version = 'v0.1'
        else:
            # found "sta_scan", didn't find "scan"
            version = 'v1.0'
        return version

    @classmethod
    def gen_connect_cmd(cls, ssid: str, password: str = '', *, bssid: str = '') -> str:
        """generate correct connect command

        Args:
            sta_dut (DutPort): which dut
            ssid (str): ssid of AP
            password (str, optional): password of AP. Defaults to ''.
            bssid (str, optional): specify bssid of AP. Defaults to None.

        Returns:
            str: connect command string
        """
        conn_cmd = 'sta_connect'
        if cls.VERSION in ['0.1', '0.0']:
            conn_cmd = 'sta'

        _cmd = f'{conn_cmd} {ssid}'
        if password:
            _cmd += f' {password}'
        if bssid:
            _cmd += f' -b {bssid}'
        return _cmd

    @classmethod
    def connect_to_ap(
        cls,
        sta_dut: DutPort,
        conn_cmd: str,
        # How to check connection succeed
        timeout: int = 30,
        wait_ip: bool = True,
        # TBD, ipv6 address is not shown in wifi-cmd yet
        # wait_ip6_num: int = 0,
    ) -> ConnectedInfo:
        # pylint: disable=too-many-arguments
        """Connect to external AP and check connected

        Args:
            sta_dut (DutPort): which dut
            conn_cmd (str): connect command
            timeout (int, optional): maximum waiting time before connected. Defaults to 30 seconds.
            wait_ip (bool, optional): Do not return until got ip. Defaults to True.
            wait_ip6_num (int, optional): TBD, please use other command to get ipv6 for now.

        Returns:
            ConnectedInfo: an object contains connected information
        """
        sta_dut.write_line(conn_cmd)

        all_expect = re.compile(
            '|'.join(
                [
                    f'(?:{p.pattern})'
                    for p in [
                        cls.WIFI_CONNECTED_PATTERN,
                        cls.GOT_IP4_PATTERN,
                        # Try to get more info from idf logs
                        cls.IDF_WIFI_CONNECTED_PATTERN,
                        cls.IDF_WIFI_CONNECTED_AP_INFO_PATTERN,
                        cls.IDF_GOT_IP4_PATTERN,
                    ]
                ]
            )
        )

        t0 = time.perf_counter()

        connected_info = ConnectedInfo(ssid=conn_cmd.split()[1])
        wifi_connected = False
        got_ip4 = False
        while time.perf_counter() - t0 < timeout:
            time_left = t0 + timeout - time.perf_counter()
            match = sta_dut.expect(all_expect, timeout=time_left)
            assert match
            data = to_str(match.group(0))
            logger.debug(f'Matched data: {data}')
            # Check which pattern was matched.
            if cls.WIFI_CONNECTED_PATTERN.match(data):
                # No extra information now
                wifi_connected = True
            elif cls.GOT_IP4_PATTERN.match(data):
                # parse ipv4 info
                _match = cls.GOT_IP4_PATTERN.match(data)
                assert _match
                connected_info.ip4 = _match.group(1)
                got_ip4 = True
            elif cls.IDF_GOT_IP4_PATTERN.match(data):
                _match = cls.IDF_GOT_IP4_PATTERN.match(data)
                assert _match
                connected_info.ip4 = _match.group(1)
                connected_info.ip4_mask = _match.group(2)
                connected_info.ip4_gw = _match.group(3)
                got_ip4 = True
            # Parse extra connection info from IDF wifi log
            elif cls.IDF_WIFI_CONNECTED_PATTERN.match(data):
                _match = re.search(r'aid = (\d+)', data)
                if _match:
                    connected_info.aid = int(_match.group(1))
                _match = re.search(r'channel (\d+), (\w+)?,?', data)
                if _match:
                    connected_info.channel = int(_match.group(1))
                    if _match.group(2):
                        connected_info.bandwidth = _match.group(2)
                _match = re.search(r'bssid = ([\w:]+)[^\w:]', data)
                if _match:
                    connected_info.bssid = _match.group(1)
            elif cls.IDF_WIFI_CONNECTED_AP_INFO_PATTERN.match(data):
                _match = cls.IDF_WIFI_CONNECTED_AP_INFO_PATTERN.match(data)
                assert _match
                connected_info.security = _match.group(1)
                connected_info.phy = _match.group(2)
                connected_info.rssi = int(_match.group(3))
            else:
                logger.warning(f'Should not happen, expect returned: {data}')

            # Already connected and got expected ip addresses.
            if wifi_connected and (not wait_ip or got_ip4):
                break
        else:
            # timeout
            logger.info(f'dut left data: {sta_dut.read_all_bytes()!r}')
            raise TimeoutError(f'station connect AP failed in {timeout} seconds.')

        # query connected info
        return connected_info
