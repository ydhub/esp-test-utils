import contextlib
from pathlib import Path
from unittest import mock

import pytest

import esptest.adapter.dut.esp_mixin as esp_mixin_module
import esptest.common.compat_typing as t
from esptest.adapter.dut.dut_base import DutConfig
from esptest.adapter.dut.esp_mixin import EspMixin


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

    mock_tool_cls.assert_called_once_with('/tmp/app.bin', '/dev/ttyUSB1', esptool='esptool')
    tool.download_partition.assert_called_once_with({'nvs': '/tmp/nvs.bin'})
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
