import re
import shutil
import time
from functools import lru_cache
from itertools import permutations

from ..common import compat_typing as t
from ..common.decorators import enhance_import_error_message
from ..common.shell import run_cmd
from ..logger import get_logger

logger = get_logger('wnic')


class Nic:
    def __init__(self, iface: str) -> None:
        self.iface = iface
        self.sniffer = None

    def reset_nic(self) -> None:
        self.iface_down()
        self.iface_up()

    def iface_up(self, sudo: bool = True) -> None:
        args = []
        if shutil.which('ifconfig'):
            args = ['ifconfig', self.iface, 'up']
        else:
            args = ['ip', 'link', 'set', self.iface, 'up']
        if sudo:
            args = ['sudo'] + args
        run_cmd(args)

    def iface_down(self, sudo: bool = True) -> None:
        args = []
        if shutil.which('ifconfig'):
            args = ['ifconfig', self.iface, 'down']
        else:
            args = ['ip', 'link', 'set', self.iface, 'down']
        if sudo:
            args = ['sudo'] + args
        run_cmd(args)

    def dhcp_start(self, sudo: bool = True) -> None:
        args = []
        if shutil.which('dhclient'):
            # args = ['dhclient', '-nw', 'eth0']
            args = ['dhclient', self.iface]
        elif shutil.which('dhcpcd'):
            args = ['dhcpcd', '-G', self.iface, '-t', '15']
        else:
            raise NotImplementedError()
        if sudo:
            args = ['sudo'] + args
        run_cmd(args)

    @staticmethod
    def kill_wpa_supplicant() -> None:
        run_cmd('sudo killall wpa_supplicant || true')

    @enhance_import_error_message('please install scapy or "pip install esp-test-utils[all]"')
    def send(self, packet, count, inter, verbose=False):  # type: ignore
        from scapy.sendrecv import sendp

        sendp(packet, iface=self.iface, verbose=verbose, inter=inter, count=count)

    @enhance_import_error_message('please install scapy or "pip install esp-test-utils[all]"')
    def start_capture(self, **kwargs):  # type: ignore
        from scapy.config import conf
        from scapy.sendrecv import AsyncSniffer

        # avoid scapy 2.6.0 get iface link type only at first init time
        conf.ifaces.reload()
        if 'filter' not in kwargs:
            logger.warning('start capture without filter! This may cause a large memory usage!')
            logger.warning('filter syntax Ref: https://biot.com/capstats/bpf.html')
            # kwargs["filter"] = "wlan src c4:4f:33:16:f9:49 or wlan src 30:ae:a4:80:62:2c"
        self.sniffer = AsyncSniffer(iface=self.iface, **kwargs)
        self.sniffer.start()
        time.sleep(1)  # make sure the operation work

    @enhance_import_error_message('please install scapy or "pip install esp-test-utils[all]"')
    def stop_capture(self, join=True):  # type: ignore
        if self.sniffer:
            pkts = self.sniffer.stop(join=join)
            self.sniffer = None
            return pkts
        return []


class WiFiNic(Nic):  # pylint: disable=too-many-public-methods
    def __init__(self, iface: str) -> None:
        super().__init__(iface)
        self.phy = self._get_phy()

    def reset_nic(self) -> None:
        self.iface_down()
        self.iw_set_type('managed')
        self.iface_up()

    def _get_phy(self) -> str:
        return self.parse_phy_interfaces()[self.iface]

    @staticmethod
    @lru_cache()
    def get_phy_info(phy: str, country: str = '') -> str:
        if country:
            WiFiNic.set_country_code(country)
        return run_cmd(f'iw {phy} info')

    @property
    def phy_info(self) -> str:
        return self.get_phy_info(self.phy)

    @property
    @lru_cache(maxsize=1)
    def supported_modes(self) -> t.List[str]:
        modes = []
        _start = False
        for line in self.phy_info.splitlines():
            if 'Supported interface modes' in line:
                _start = True
                continue
            if _start:
                if not line.strip().startswith('*'):
                    # there's only one line include "Supported interface modes"
                    break
                modes.append(line.replace('*', '').strip())
        return modes

    def is_ap_supported(self) -> bool:
        return 'AP' in self.supported_modes

    def is_he_supported(self) -> bool:
        return 'HTC HE Supported' in self.phy_info

    @property
    @lru_cache(maxsize=1)
    def channels(self) -> t.Dict[str, t.Set[int]]:
        channels: t.Dict[str, t.Set[int]] = {
            'all': set(),
            'radar detection': set(),
            'disabled': set(),
            'no IR': set(),
        }
        _start = False
        for line in self.phy_info.splitlines():
            if 'Frequencies' in line:
                _start = True
                continue
            if _start:
                match = re.search(r'MHz \[(\d+)\]', line)
                if not line.strip().startswith('*') or not match:
                    # continue for 5G Frequencies
                    _start = False
                    continue
                cur_ch = int(match.group(1))
                channels['all'].add(cur_ch)
                for typ, val in channels.items():
                    if typ in line:
                        val.add(cur_ch)
        return channels

    @property
    def send_channels(self) -> t.List[int]:
        _disabled_chs = self.channels['radar detection'] | self.channels['disabled'] | self.channels['no IR']
        ch_set = self.channels['all'].difference(_disabled_chs)
        return list(ch_set)

    @property
    def capture_channels(self) -> t.List[int]:
        ch_set = self.channels['all'].difference(self.channels['disabled'])
        return list(ch_set)

    def iw_set_type(self, if_type: str) -> None:
        """Set interface type: managed, monitor, etc..."""
        args = ['sudo', 'iw', 'dev', self.iface, 'set', 'type', if_type]
        run_cmd(args)

    def set_channel(self, channel: int, bw: str = '') -> None:
        """Start wifi nic channel, bw can be [NOHT|HT20|HT40+|HT40-|5MHz|10MHz|80MHz]"""
        args = ['sudo', 'iw', 'dev', self.iface, 'set', 'channel', str(channel)]
        if bw:
            args += [bw]
        run_cmd(args)

    def set_rate(self, rate: float, short_gi: bool = False) -> None:
        dot11b_rates = [1, 2, 5.5, 11]
        dot11g_rates = [6, 9, 12, 18, 24, 36, 48, 54]
        dot11n_ht20_short_gi_rates = [7.2, 14.4, 21.7, 28.9, 43.3, 57.8, 65, 72.2]
        dot11n_ht20_long_gi_rates = [6.5, 13, 19.5, 26, 39, 52, 58.5, 65]
        dot11n_ht40_short_gi_rates = [15, 30, 45, 60, 90, 120, 135, 150]
        dot11n_ht40_long_gi_rates = [13.5, 27, 40.5, 54, 81, 108, 121.5, 135]

        args = []
        if rate in dot11b_rates or rate in dot11g_rates:
            args = ['sudo', 'iw', 'dev', self.iface, 'set', 'bitrates', 'legacy-2.4', str(rate)]
        elif rate in dot11n_ht20_short_gi_rates + dot11n_ht40_short_gi_rates and short_gi:
            args = ['sudo', 'iw', 'dev', self.iface, 'set', 'bitrates', 'ht-mcs-2.4', str(rate), 'sgi-2.4']
        elif rate in dot11n_ht20_long_gi_rates + dot11n_ht40_long_gi_rates and not short_gi:
            args = ['sudo', 'iw', 'dev', self.iface, 'set', 'bitrates', 'ht-mcs-2.4', str(rate), 'lgi-2.4']
        else:
            raise ValueError(f'Invalid rate: {rate}! please check!')
        run_cmd(args)

    def nic_ready(self, channel: int, rate: float = 0, short_gi: bool = False, bw: str = '') -> None:
        self.iface_down()
        self.iface_up()
        self.set_channel(channel, bw)
        if rate:
            self.set_rate(rate, short_gi)

    def monitor_ready(self, channel: int, bw: str = '') -> None:
        """Start wifi nic to monitor mode

        Args:
            channel (int): monitor channel to set
            bw (str, optional): [NOHT|HT20|HT40+|HT40-|5MHz|10MHz|80MHz]. Defaults to 'HT20'.
        """
        # AX200 sometime set monitor mode failed if wpa_supplicant process is running
        self.kill_wpa_supplicant()
        self.iface_down()
        self.iw_set_type('monitor')
        self.iface_up()
        self.set_channel(channel, bw)

    @staticmethod
    @lru_cache(maxsize=1)
    def iw_dev() -> str:
        """List all network interfaces for wireless hardware."""
        return run_cmd('iw dev')

    @staticmethod
    def set_country_code(country_code: str = '') -> None:
        """Need set country before get full supported channels"""
        run_cmd(['sudo', 'iw', 'reg', 'set', country_code])

    @staticmethod
    @lru_cache(maxsize=1)
    def iw_reg_get() -> str:
        """Print out the kernel's current regulatory domain information."""
        return run_cmd('iw reg get')

    @staticmethod
    @lru_cache(maxsize=1)
    def get_region_global() -> str:
        """get global country"""
        # find first ":"
        reg_info = WiFiNic.iw_reg_get()
        _index = reg_info.find(':')
        return reg_info[_index - 2 : _index]

    @staticmethod
    @lru_cache(maxsize=1)
    def get_region_self_managed() -> str:
        _cmd = 'iw reg get | grep self-managed'
        output = run_cmd(_cmd)
        return output.split(' ', maxsplit=1)[0]

    # functools.cache is supported from python3.9
    @classmethod
    def parse_phy_interfaces(cls) -> t.Dict[str, str]:
        dev_phy_map = {}
        current_phy = ''
        for line in cls.iw_dev().splitlines():
            line = line.strip()
            if line.startswith('phy#'):
                current_phy = line
            elif line.startswith('Interface '):
                assert current_phy
                iface = line.split(' ')[1]
                dev_phy_map[iface] = current_phy
        return dev_phy_map

    @classmethod
    def get_wlan_interfaces(cls) -> t.List[str]:
        return list(cls.parse_phy_interfaces().keys())

    @classmethod
    def get_tx_and_rx_iface_pair(cls, channel: int, country: str = '') -> t.Tuple[str, str]:
        """Get a pair of interface for send/monitor"""
        if country:
            cls.set_country_code(country)
        ifaces = cls.get_wlan_interfaces()
        for tx_iface, rx_iface in permutations(ifaces, 2):
            if channel not in cls(tx_iface).send_channels:
                continue
            if channel not in cls(rx_iface).capture_channels:
                continue
            return tx_iface, rx_iface
        raise ValueError('no available interfaces for tx/rx')

    @classmethod
    def get_first_interface(cls, mode: str, channel: int = 0, country: str = '') -> str:
        """Get interface, mode: ap, send, capture, he"""
        mode = mode.lower()  # allow uppercase
        assert mode in ['ap', 'send', 'capture', 'he']
        if country:
            cls.set_country_code(country)
        ifaces = cls.get_wlan_interfaces()
        # currently channel is only used for send/capture modes
        for iface in ifaces:
            if mode == 'ap':
                assert channel
                if cls(iface).is_ap_supported():
                    if channel in cls(iface).send_channels:
                        return iface
            elif mode == 'he':
                if cls(iface).is_he_supported():
                    # check channel if set
                    if not channel or channel in cls(iface).send_channels:
                        return iface
            elif mode == 'send':
                assert channel
                if channel in cls(iface).send_channels:
                    return iface
            elif mode == 'capture':
                assert channel
                if channel in cls(iface).capture_channels:
                    return iface
        raise ValueError('Unknown error!')
