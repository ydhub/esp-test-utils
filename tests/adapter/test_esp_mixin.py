import contextlib
from pathlib import Path
from unittest import mock

import pytest
import serial

import esptest.adapter.dut.download_log as download_log_module
import esptest.adapter.dut.esp_mixin as esp_mixin_module
import esptest.common.compat_typing as t
from esptest.adapter.dut.dut_base import DutConfig
from esptest.adapter.dut.esp_mixin import EspMixin, default_download_log_file


class _ChangeSerialParent:
    def __init__(self) -> None:
        self.parent_change_kwargs: t.Optional[t.Dict[str, t.Any]] = None

    def change_serial_config(self, **kwargs: t.Any) -> None:
        self.parent_change_kwargs = kwargs


class EspMixinHarness(_ChangeSerialParent):
    """Plain host for EspMixin methods via unbound calls (avoids DutBase property conflicts)."""

    def __init__(
        self,
        dut_config: DutConfig,
        esp: t.Any = None,
        log_file: str = '',
    ) -> None:
        super().__init__()
        self.dut_config = dut_config
        self.downbin_tool: t.Optional[t.Any] = None
        self._esp = esp
        self._log_file = log_file
        self.hard_reset_calls = 0
        self._chip_info = None
        self._download_port: t.Optional[t.Any] = None

    @property
    def esp(self) -> t.Any:
        return self._esp

    @property
    def bin_path(self) -> t.Any:
        return self.dut_config.bin_path

    @property
    def name(self) -> str:
        return self.dut_config.name or 'harness'

    @property
    def log_file(self) -> str:
        return self._log_file

    @property
    def download_log_file(self) -> str:
        result = EspMixin.download_log_file.__get__(self, type(self))  # type: ignore[misc]
        assert isinstance(result, str)
        return result

    def _append_download_log(self, text: str) -> None:
        EspMixin._append_download_log(self, text)  # type: ignore[arg-type]

    @contextlib.contextmanager
    def _borrow_download_port(self, reason: str) -> t.Generator[None, None, None]:
        with EspMixin._borrow_download_port(self, reason):  # type: ignore[arg-type]
            yield

    @contextlib.contextmanager
    def disable_redirect_thread(self) -> t.Generator[None, None, None]:
        yield

    def hard_reset(self) -> None:
        self.hard_reset_calls += 1


class EspMixinSuperHarness(EspMixin, _ChangeSerialParent):
    """Needed only where EspMixin.change_serial_config uses super()."""

    def __init__(self, dut_config: DutConfig) -> None:
        _ChangeSerialParent.__init__(self)
        self.dut_config = dut_config  # type: ignore[misc]
        self._esp = None
        self.downbin_tool = None

    @property
    def esp(self) -> t.Any:
        return self._esp


def _make_esp(is_stub: bool = True, chip_name: str = 'ESP32') -> mock.MagicMock:
    esp = mock.MagicMock()
    esp.IS_STUB = is_stub
    esp.CHIP_NAME = chip_name
    esp._port = mock.MagicMock()
    esp._port.port = '/dev/ttyUSB0'
    esp._port.baudrate = 115200
    return esp


def test_download_bin_raises_when_bin_path_missing() -> None:
    harness = EspMixinHarness(DutConfig(name='dut'))
    with pytest.raises(ValueError, match='bin path not set'):
        EspMixin.download_bin(harness)  # type: ignore[arg-type]


def test_download_bin_creates_tool_and_downloads() -> None:
    tool = mock.MagicMock()
    tool.force_no_stub = False
    esp = _make_esp(is_stub=True, chip_name='ESP32')
    cfg = DutConfig(name='dut', download_device='/dev/ttyUSB0', use_esptool='esptool')
    # Assign after __post_init__ to avoid ParseBinPath on a fake path.
    cfg.bin_path = '/tmp/app.bin'
    harness = EspMixinHarness(cfg, esp=esp)

    with mock.patch.object(esp_mixin_module, 'DownBinTool', return_value=tool) as mock_tool_cls:
        EspMixin.download_bin(
            harness,  # type: ignore[arg-type]
            False,  # positional erase_nvs (backward compatible)
            baud=[460800, 115200],
            force_no_stub=True,
        )

    mock_tool_cls.assert_called_once_with(
        '/tmp/app.bin',
        '/dev/ttyUSB0',
        esptool='esptool',
        erase_nvs=False,
        baud=[460800, 115200],
        force_no_stub=True,
        output_log='',
    )
    tool.download.assert_called_once()
    assert harness.hard_reset_calls == 1
    assert harness.downbin_tool is tool


def test_download_bin_overwrites_bin_path_and_sets_log_baud() -> None:
    tool = mock.MagicMock()
    esp = _make_esp(is_stub=True, chip_name='ESP32')
    cfg = DutConfig(name='dut', download_device='/dev/ttyUSB0')
    cfg.bin_path = '/tmp/old.bin'
    harness = EspMixinHarness(cfg, esp=esp)
    # keep Python 3.7-compatible multi-context with-statement
    # fmt: off
    with mock.patch.object(esp_mixin_module, 'DownBinTool', return_value=tool), \
        mock.patch.object(harness, 'change_serial_config') as change_cfg:
        EspMixin.download_bin(harness, bin_path='/tmp/new.bin', log_port_baudrate=74880)  # type: ignore[arg-type]
    # fmt: on

    assert harness.dut_config.bin_path == '/tmp/new.bin'
    tool.download.assert_called_once()
    change_cfg.assert_called_once_with(baudrate=74880)


def test_download_bin_forces_no_stub_for_non_esp32_rom() -> None:
    tool = mock.MagicMock()
    tool.force_no_stub = False
    esp = _make_esp(is_stub=False, chip_name='ESP32-C3')
    cfg = DutConfig(name='dut', download_device='/dev/ttyUSB0')
    cfg.bin_path = '/tmp/app.bin'
    harness = EspMixinHarness(cfg, esp=esp)

    with mock.patch.object(esp_mixin_module, 'DownBinTool', return_value=tool):
        EspMixin.download_bin(harness)  # type: ignore[arg-type]

    assert tool.force_no_stub is True


def test_download_partition_raises_when_tool_unavailable() -> None:
    harness = EspMixinHarness(DutConfig(name='dut'))
    with pytest.raises(ValueError, match='bin path not set'):
        EspMixin.download_partition(harness, {'nvs': '/tmp/nvs.bin'})  # type: ignore[arg-type]


def test_download_partition_creates_tool_from_bin_path() -> None:
    tool = mock.MagicMock()
    tool.force_no_stub = False
    esp = _make_esp(is_stub=True, chip_name='ESP32')
    cfg = DutConfig(name='dut', download_device='/dev/ttyUSB1', use_esptool='esptool')
    cfg.bin_path = '/tmp/app.bin'
    harness = EspMixinHarness(cfg, esp=esp)

    with mock.patch.object(esp_mixin_module, 'DownBinTool', return_value=tool) as mock_tool_cls:
        EspMixin.download_partition(harness, {'nvs': '/tmp/nvs.bin'})  # type: ignore[arg-type]

    mock_tool_cls.assert_called_once_with('/tmp/app.bin', '/dev/ttyUSB1', esptool='esptool', output_log='')
    tool.download_partition.assert_called_once_with({'nvs': '/tmp/nvs.bin'}, baud=0)
    assert harness.hard_reset_calls == 1


def test_download_partition_forwards_baud() -> None:
    tool = mock.MagicMock()
    tool.force_no_stub = False
    esp = _make_esp(is_stub=True, chip_name='ESP32')
    cfg = DutConfig(name='dut', download_device='/dev/ttyUSB1', use_esptool='esptool')
    cfg.bin_path = '/tmp/app.bin'
    harness = EspMixinHarness(cfg, esp=esp)

    with mock.patch.object(esp_mixin_module, 'DownBinTool', return_value=tool):
        EspMixin.download_partition(harness, {'nvs': '/tmp/nvs.bin'}, baud=[460800, 115200])  # type: ignore[arg-type]

    tool.download_partition.assert_called_once_with({'nvs': '/tmp/nvs.bin'}, baud=[460800, 115200])
    assert harness.hard_reset_calls == 1


def test_change_serial_config_applies_to_esp_port(tmp_path: Path) -> None:
    esp = _make_esp()
    log_file = str(tmp_path / 'dut.log')
    harness = EspMixinHarness(DutConfig(name='dut'), esp=esp, log_file=log_file)

    EspMixin.change_serial_config(harness, baudrate=9600)  # type: ignore[arg-type]

    esp._port.apply_settings.assert_called_once_with({'baudrate': 9600})
    content = Path(log_file).read_text(encoding='utf-8')
    assert 'change serial config' in content
    assert '9600' in content


def test_change_serial_config_delegates_when_no_esp() -> None:
    harness = EspMixinSuperHarness(DutConfig(name='dut'))
    harness.change_serial_config(baudrate=115200)
    assert harness.parent_change_kwargs == {'baudrate': 115200}


def test_hard_reset_raises_when_unavailable() -> None:
    harness = EspMixinHarness(DutConfig(name='dut', device=''), esp=None)
    with pytest.raises(OSError, match='hard reset is not available'):
        EspMixin.hard_reset(harness)  # type: ignore[arg-type]


def test_hard_reset_uses_download_device_when_no_esp() -> None:
    cfg = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB1', support_esptool=True)
    harness = EspMixinHarness(cfg, esp=None)
    chip = mock.MagicMock()
    detect_cm = mock.MagicMock()
    detect_cm.__enter__.return_value = chip
    detect_cm.__exit__.return_value = None

    with mock.patch.object(esp_mixin_module, 'esptool_detect_chip', return_value=detect_cm) as detect:
        EspMixin.hard_reset(harness)  # type: ignore[arg-type]

    detect.assert_called_once_with('/dev/ttyUSB1')
    chip.hard_reset.assert_called_once()


def test_hard_reset_requires_support_esptool_without_esp() -> None:
    cfg = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB1', support_esptool=False)
    harness = EspMixinHarness(cfg, esp=None)
    with pytest.raises(OSError, match='hard reset is not available'):
        EspMixin.hard_reset(harness)  # type: ignore[arg-type]


def test_hard_reset_reuses_esp_when_download_matches_log() -> None:
    esp = _make_esp()
    cfg = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB0')
    harness = EspMixinHarness(cfg, esp=esp)

    EspMixin.hard_reset(harness)  # type: ignore[arg-type]

    esp.hard_reset.assert_called_once()


def test_log_port_hosts_esp() -> None:
    from esptest.adapter.dut.esp_mixin import log_port_hosts_esp

    same = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB0', support_esptool=True)
    assert log_port_hosts_esp(same) is True

    unset = DutConfig(name='dut', device='/dev/ttyUSB0', support_esptool=True)
    assert log_port_hosts_esp(unset) is True

    no_flag = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB0', support_esptool=False)
    assert log_port_hosts_esp(no_flag) is False

    dual = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB1', support_esptool=True)
    with mock.patch.object(download_log_module, 'compute_serial_port', side_effect=lambda p: p):
        assert log_port_hosts_esp(dual) is False


def test_dut_config_auto_download_log_file_for_dual_uart(tmp_path: Path) -> None:
    log_file = str(tmp_path / 'AT1_123.log')
    cfg = DutConfig(
        name='AT1',
        device='/dev/ttyUSB0',
        download_device='/dev/ttyUSB1',
        log_file=log_file,
    )
    assert cfg.save_download_log is True
    assert cfg.download_log_file == str(tmp_path / 'AT1_download_123.log')
    assert isinstance(cfg.download_serial_configs, dict)
    assert 'timeout' in cfg.download_serial_configs


def test_dut_config_skips_download_log_when_same_port(tmp_path: Path) -> None:
    cfg = DutConfig(
        name='dut',
        device='/dev/ttyUSB0',
        download_device='/dev/ttyUSB0',
        log_file=str(tmp_path / 'dut.log'),
    )
    assert cfg.download_log_file == ''


def test_dut_config_save_download_log_false_skips_auto_path(tmp_path: Path) -> None:
    cfg = DutConfig(
        name='dut',
        device='/dev/ttyUSB0',
        download_device='/dev/ttyUSB1',
        log_file=str(tmp_path / 'dut.log'),
        save_download_log=False,
    )
    assert cfg.download_log_file == ''


def test_dut_config_keeps_explicit_download_log_file(tmp_path: Path) -> None:
    explicit = str(tmp_path / 'custom_dl.log')
    cfg = DutConfig(
        name='dut',
        device='/dev/ttyUSB0',
        download_device='/dev/ttyUSB1',
        log_file=str(tmp_path / 'dut.log'),
        download_log_file=explicit,
    )
    assert cfg.download_log_file == explicit


def test_default_download_log_file_derives_when_config_path_empty(tmp_path: Path) -> None:
    """Re-derive path from log_file name when download_log_file was cleared."""
    log_file = str(tmp_path / 'AT1_123.log')
    cfg = DutConfig(
        name='AT1',
        device='/dev/ttyUSB0',
        download_device='/dev/ttyUSB1',
        log_file=log_file,
    )
    cfg.download_log_file = ''
    with mock.patch.object(download_log_module, 'compute_serial_port', side_effect=lambda p: p):
        assert default_download_log_file(cfg) == str(tmp_path / 'AT1_download_123.log')


def test_borrow_download_port_pauses_serial_and_appends_marker(tmp_path: Path) -> None:
    dl_log = str(tmp_path / 'dut_download.log')
    cfg = DutConfig(
        name='dut',
        device='/dev/ttyUSB0',
        download_device='/dev/ttyUSB1',
        log_file=str(tmp_path / 'dut.log'),
        download_log_file=dl_log,
    )
    harness = EspMixinHarness(cfg)
    download_port = mock.MagicMock()
    download_port.log_file = dl_log
    download_port.stop_redirect_thread.return_value = True
    ser = mock.MagicMock()
    ser.is_open = True

    def _close_serial() -> None:
        ser.is_open = False

    ser.close.side_effect = _close_serial
    download_port.serial = ser
    harness._download_port = download_port  # pylint: disable=protected-access

    with mock.patch.object(harness, 'disable_redirect_thread') as disable_log:
        with mock.patch.object(download_log_module, 'compute_serial_port', side_effect=lambda p: p):
            with EspMixin._borrow_download_port(harness, 'hard_reset'):  # type: ignore[arg-type]
                assert ser.close.called
                assert download_port.stop_redirect_thread.called

    # Dual-UART: log redirect must keep running.
    disable_log.assert_not_called()
    download_port.start_redirect_thread.assert_called_once()
    ser.open.assert_called_once()
    content = Path(dl_log).read_text(encoding='utf-8')
    assert 'hard_reset' in content
    assert 'begin' in content
    assert 'end' in content


def test_borrow_download_port_disables_log_redirect_when_same_port() -> None:
    cfg = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB0')
    harness = EspMixinHarness(cfg)
    disable = mock.MagicMock()
    disable.return_value.__enter__ = mock.MagicMock(return_value=None)
    disable.return_value.__exit__ = mock.MagicMock(return_value=None)

    with mock.patch.object(harness, 'disable_redirect_thread', disable):
        with EspMixin._borrow_download_port(harness, 'download_bin'):  # type: ignore[arg-type]
            pass

    disable.assert_called_once()


def test_hard_reset_borrows_download_port_when_dual_uart() -> None:
    cfg = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB1', support_esptool=True)
    harness = EspMixinHarness(cfg, esp=None)
    borrow = mock.MagicMock()
    borrow.return_value.__enter__ = mock.MagicMock(return_value=None)
    borrow.return_value.__exit__ = mock.MagicMock(return_value=None)
    chip = mock.MagicMock()
    chip.__enter__.return_value = chip
    chip.__exit__.return_value = None

    # fmt: off
    with mock.patch.object(harness, '_borrow_download_port', borrow), \
        mock.patch.object(esp_mixin_module, 'esptool_detect_chip', return_value=chip):
        EspMixin.hard_reset(harness)  # type: ignore[arg-type]
    # fmt: on

    borrow.assert_called_once_with('hard_reset')
    chip.hard_reset.assert_called_once()


def test_esp_dut_creates_download_port_for_dual_uart(tmp_path: Path) -> None:
    import esptest.adapter.dut.esp_dut as esp_dut_module
    from esptest.adapter.dut.esp_dut import EspDut
    from esptest.adapter.port.serial_port import SerialPort

    log_file = str(tmp_path / 'dut.log')
    cfg = DutConfig(
        name='dut',
        device='loop://',
        download_device='loop://download',
        support_esptool=True,
        baudrate=115200,
        log_file=log_file,
        download_serial_configs={'timeout': 0.01},
    )
    dut = object.__new__(EspDut)
    dut._dut_config = cfg  # pylint: disable=protected-access
    dut._kwargs = {}
    dut._raw_port = None
    dut._download_port = None
    base_port = None
    download_port = None
    try:
        with mock.patch.object(esp_dut_module, 'compute_serial_port', side_effect=lambda p, strict=False: p):
            with mock.patch.object(esp_mixin_module, 'compute_serial_port', side_effect=lambda p, strict=False: p):
                base_port = EspDut._create_base_port(dut)
                download_port = EspMixin._create_download_port(dut)  # type: ignore[arg-type]
                dut._download_port = download_port
        assert isinstance(base_port, SerialPort)
        assert isinstance(download_port, SerialPort)
        assert download_port.log_file.endswith('dut_download.log')
        assert download_port.name == 'dut_download'
    finally:
        if download_port:
            download_port.close()
        if base_port:
            base_port.close()
        raw = getattr(dut, '_raw_port', None)
        if raw is not None and getattr(raw, 'is_open', False):
            raw.close()


def test_esp_dut_dual_uart_uses_serial_log_port() -> None:
    import esptest.adapter.dut.esp_dut as esp_dut_module
    from esptest.adapter.dut.esp_dut import EspDut
    from esptest.adapter.port.serial_port import SerialPort

    cfg = DutConfig(
        name='dut',
        device='loop://',
        download_device='/dev/ttyUSB1',
        support_esptool=True,
        baudrate=115200,
    )
    dut = object.__new__(EspDut)
    dut._dut_config = cfg  # pylint: disable=protected-access
    dut._kwargs = {}
    dut._raw_port = None
    base_port = None
    try:
        with mock.patch.object(esp_dut_module, 'compute_serial_port', side_effect=lambda p, strict=False: p):
            with mock.patch.object(download_log_module, 'compute_serial_port', side_effect=lambda p: p):
                base_port = EspDut._create_base_port(dut)
        assert isinstance(base_port, SerialPort)
        assert isinstance(dut._raw_port, serial.SerialBase)
        assert dut._raw_port.port == 'loop://'
    finally:
        if base_port:
            base_port.close()
        raw = getattr(dut, '_raw_port', None)
        if raw is not None and getattr(raw, 'is_open', False):
            raw.close()


def test_get_chip_info_uses_detect_one_port() -> None:
    from esptest.devices.esp_serial import EspPortInfo

    detected = EspPortInfo(
        '/dev/ttyUSB0',
        '1-1.2',
        True,
        chip_name='ESP32-C3',
        chip_rev_full=4,
        target='esp32c3',
    )
    port_meta = mock.MagicMock(device='/dev/ttyUSB0', location='1-1.2', description='USB')
    cfg = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB0')
    harness = EspMixinHarness(cfg, esp=None)

    # fmt: off
    with mock.patch.object(esp_mixin_module, 'get_serial_port_info', return_value=port_meta), \
        mock.patch.object(esp_mixin_module, 'detect_one_port', return_value=detected) as detect:
        info = EspMixin.get_chip_info(harness)  # type: ignore[arg-type]
        cached = EspMixin.get_chip_info(harness)  # type: ignore[arg-type]
    # fmt: on

    detect.assert_called_once_with(port_meta)
    assert info is cached is detected
    assert info.chip_rev_full == 4


def test_get_chip_info_falls_back_to_esp_serial_port() -> None:
    from esptest.devices.esp_serial import EspPortInfo

    esp = _make_esp()
    esp.serial_port = '/dev/ttyUSB0'
    detected = EspPortInfo('/dev/ttyUSB0', '', True, chip_name='ESP32', chip_rev_full=300, target='esp32')
    cfg = DutConfig(name='dut', device='socket://host:1234', download_device='socket://host:1234')
    harness = EspMixinHarness(cfg, esp=esp)

    # fmt: off
    with mock.patch.object(
        esp_mixin_module, 'get_serial_port_info', side_effect=serial.SerialException('missing'),
    ), mock.patch.object(
        esp_mixin_module, 'detect_port_info_no_cache', return_value=detected,
    ) as detect:
        info = EspMixin.get_chip_info(harness)  # type: ignore[arg-type]
    # fmt: on

    detect.assert_called_once_with('/dev/ttyUSB0')
    assert info is detected
    assert info.chip_rev_full == 300
    assert harness._chip_info is info


def test_get_chip_info_uses_download_device_when_ports_differ_without_esp() -> None:
    """Separate download/log UARTs: no self.esp; detect the download device directly."""
    from esptest.devices.esp_serial import EspPortInfo

    detected = EspPortInfo('/dev/ttyUSB1', '', True, chip_name='ESP32', chip_rev_full=100, target='esp32')
    cfg = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB1')
    harness = EspMixinHarness(cfg, esp=None)

    # fmt: off
    with mock.patch.object(
        esp_mixin_module, 'get_serial_port_info', side_effect=serial.SerialException('missing'),
    ), mock.patch.object(
        esp_mixin_module, 'detect_port_info_no_cache', return_value=detected,
    ) as detect:
        info = EspMixin.get_chip_info(harness)  # type: ignore[arg-type]
    # fmt: on

    detect.assert_called_once_with('/dev/ttyUSB1')
    assert info is detected


def test_get_chip_info_raises_when_detect_fails() -> None:
    from esptest.devices.esp_serial import EspPortInfo

    failed = EspPortInfo('/dev/ttyUSB0', '', False, chip_description='esptool FatalError: boom')
    port_meta = mock.MagicMock(device='/dev/ttyUSB0', location='', description='')
    cfg = DutConfig(name='dut', device='/dev/ttyUSB0', download_device='/dev/ttyUSB0')
    harness = EspMixinHarness(cfg, esp=None)

    # fmt: off
    with mock.patch.object(esp_mixin_module, 'get_serial_port_info', return_value=port_meta), \
        mock.patch.object(esp_mixin_module, 'detect_one_port', return_value=failed):
        with pytest.raises(OSError, match='esptool FatalError'):
            EspMixin.get_chip_info(harness)  # type: ignore[arg-type]
    # fmt: on
    assert harness._chip_info is None


def test_get_chip_info_raises_when_port_and_esp_unavailable() -> None:
    from esptest.devices.esp_serial import EspPortInfo

    cfg = DutConfig(name='dut', device='/dev/ttyUSB9', download_device='/dev/ttyUSB9')
    harness = EspMixinHarness(cfg, esp=None)
    failed = EspPortInfo('/dev/ttyUSB9', '', False, chip_description='esptool detect failed')
    # fmt: off
    with mock.patch.object(
        esp_mixin_module, 'get_serial_port_info', side_effect=serial.SerialException('missing'),
    ), mock.patch.object(esp_mixin_module, 'detect_port_info_no_cache', return_value=failed):
        with pytest.raises(OSError, match='esptool detect failed'):
            EspMixin.get_chip_info(harness)  # type: ignore[arg-type]
    # fmt: on


def test_get_chip_info_raises_when_unavailable() -> None:
    harness = EspMixinHarness(DutConfig(name='dut', device=''), esp=None)
    with pytest.raises(OSError, match='no serial device configured'):
        EspMixin.get_chip_info(harness)  # type: ignore[arg-type]


class _RedirectParent:
    """Minimal parent so EspMixin.stop/start_redirect_thread can call super()."""

    def __init__(self) -> None:
        self.spawn_running = True
        self.stop_calls = 0
        self.start_calls = 0

    def stop_redirect_thread(self) -> bool:
        self.stop_calls += 1
        was_running = self.spawn_running
        self.spawn_running = False
        return was_running

    def start_redirect_thread(self) -> None:
        self.start_calls += 1
        self.spawn_running = True


class EspMixinRedirectHarness(EspMixin, _RedirectParent):
    def __init__(self, esp: t.Any = None, log_file: str = '') -> None:
        _RedirectParent.__init__(self)
        self.dut_config = DutConfig(name='dut')  # type: ignore[misc]
        self._esp = esp
        self._log_file = log_file
        self.downbin_tool = None

    @property
    def esp(self) -> t.Any:
        return self._esp

    @property
    def log_file(self) -> str:
        return self._log_file


def test_esp_mixin_stop_redirect_stops_spawn_when_port_already_closed() -> None:
    """Closed serial must not skip stopping spawn (otherwise expect has no redirect)."""
    esp = _make_esp()
    esp._port.is_open = False
    harness = EspMixinRedirectHarness(esp=esp)
    harness.spawn_running = True

    stopped = harness.stop_redirect_thread()

    assert harness.stop_calls == 1
    assert harness.spawn_running is False
    # spawn was running: report stopped so disable_redirect_thread will restart it
    assert stopped is True
    esp._port.close.assert_not_called()


def test_esp_mixin_stop_redirect_closes_open_port_and_allows_restart() -> None:
    esp = _make_esp()
    esp._port.is_open = True
    harness = EspMixinRedirectHarness(esp=esp)

    stopped = harness.stop_redirect_thread()
    assert stopped is True
    assert harness.spawn_running is False
    esp._port.close.assert_called_once()

    harness.start_redirect_thread()
    assert harness.spawn_running is True
    esp._port.open.assert_called_once()
