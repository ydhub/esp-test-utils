from pathlib import Path
from typing import Tuple
from unittest import mock

import pytest

import esptest.tools.download_bin as download_bin_module
from esptest.tools.download_bin import BinConfig, DownBinTool, download_bin_to_ports, download_bins
from esptest.utility.parse_bin_path import bin_path_to_dir as bin_path_to_dir_canonical


# 使用 patch.object(module, ...) 而非 patch('esptest.tools...')，避免 Py 3.7 下 esptest.tools 未加载时的 AttributeError
# @mock.patch('esptest.tools.download_bin.DownBinTool')
@mock.patch.object(download_bin_module, 'DownBinTool')
def test_download_bin_to_ports_calls_down_tool_per_port(
    mock_down_bin_tool: mock.MagicMock,
) -> None:
    """download_bin_to_ports 应对每个 port 用同一 bin_path 创建 DownBinTool 并调用 download。"""
    bin_path = '/path/to/bin'
    ports = ['/dev/ttyUSB0', '/dev/ttyUSB1']
    download_bin_to_ports(bin_path, ports, erase_nvs=True, max_workers=2)
    assert mock_down_bin_tool.call_count == 2
    mock_down_bin_tool.assert_any_call(
        bin_path,
        '/dev/ttyUSB0',
        baud=0,
        erase_nvs=True,
        esptool='',
        force_no_stub=False,
        check_no_stub=False,
    )
    mock_down_bin_tool.assert_any_call(
        bin_path,
        '/dev/ttyUSB1',
        baud=0,
        erase_nvs=True,
        esptool='',
        force_no_stub=False,
        check_no_stub=False,
    )
    assert mock_down_bin_tool.return_value.download.call_count == 2


@mock.patch.object(download_bin_module, 'DownBinTool')
def test_download_bins_calls_down_tool_per_config(
    mock_down_bin_tool: mock.MagicMock,
) -> None:
    """download_bins 应对每个 BinConfig 创建 DownBinTool 并调用 download。"""
    configs = [
        BinConfig(bin_path='/path/to/bin1', port='/dev/ttyUSB0'),
        BinConfig(bin_path='/path/to/bin2', port='/dev/ttyUSB1', erase_nvs=False),
    ]
    download_bins(configs, max_workers=2)
    assert mock_down_bin_tool.call_count == 2
    mock_down_bin_tool.assert_any_call(
        '/path/to/bin1',
        '/dev/ttyUSB0',
        baud=0,
        erase_nvs=True,
        esptool='',
        force_no_stub=False,
        check_no_stub=False,
    )
    mock_down_bin_tool.assert_any_call(
        '/path/to/bin2',
        '/dev/ttyUSB1',
        baud=0,
        erase_nvs=False,
        esptool='',
        force_no_stub=False,
        check_no_stub=False,
    )
    assert mock_down_bin_tool.return_value.download.call_count == 2


@mock.patch.object(download_bin_module, 'DownBinTool')
def test_download_bins_empty_list(mock_down_bin_tool: mock.MagicMock) -> None:
    """空配置列表时不应创建 DownBinTool，不抛错。"""
    download_bins([], max_workers=1)
    mock_down_bin_tool.assert_not_called()


@mock.patch.object(download_bin_module, 'DownBinTool')
def test_download_bins_default_max_workers(mock_down_bin_tool: mock.MagicMock) -> None:
    """单配置时创建一次 DownBinTool 并调用 download。"""
    configs = [BinConfig(bin_path='/bin/path', port='/dev/ttyUSB0')]
    download_bins(configs)
    mock_down_bin_tool.assert_called_once_with(
        '/bin/path',
        '/dev/ttyUSB0',
        baud=0,
        erase_nvs=True,
        esptool='',
        force_no_stub=False,
        check_no_stub=False,
    )
    mock_down_bin_tool.return_value.download.assert_called_once()


@mock.patch.object(download_bin_module, 'DownBinTool')
def test_download_bins_bin_config_options(mock_down_bin_tool: mock.MagicMock) -> None:
    """BinConfig 的 erase_nvs/force_no_stub/check_no_stub 应传入 DownBinTool。"""
    configs = [
        BinConfig(
            bin_path='/path/bin',
            port='/dev/ttyUSB0',
            erase_nvs=False,
            force_no_stub=True,
            check_no_stub=True,
        ),
    ]
    download_bins(configs, max_workers=1)
    mock_down_bin_tool.assert_called_once_with(
        '/path/bin',
        '/dev/ttyUSB0',
        baud=0,
        erase_nvs=False,
        esptool='',
        force_no_stub=True,
        check_no_stub=True,
    )
    mock_down_bin_tool.return_value.download.assert_called_once()


@mock.patch.object(download_bin_module, 'DownBinTool')
def test_download_bin_to_ports_passes_baud_to_down_tool(mock_down_bin_tool: mock.MagicMock) -> None:
    """download_bin_to_ports 的 baud 参数应透传给 DownBinTool。"""
    download_bin_to_ports('/path/to/bin', ['/dev/ttyUSB0'], baud=[460800, 115200], max_workers=1)
    mock_down_bin_tool.assert_called_once_with(
        '/path/to/bin',
        '/dev/ttyUSB0',
        baud=[460800, 115200],
        erase_nvs=True,
        esptool='',
        force_no_stub=False,
        check_no_stub=False,
    )


@mock.patch.object(download_bin_module, 'DownBinTool')
def test_download_bins_bin_config_baud_is_forwarded(mock_down_bin_tool: mock.MagicMock) -> None:
    """download_bins 应将 BinConfig.baud 透传到 DownBinTool。"""
    configs = [BinConfig(bin_path='/path/bin', port='/dev/ttyUSB0', baud=921600)]
    download_bins(configs, max_workers=1)
    mock_down_bin_tool.assert_called_once_with(
        '/path/bin',
        '/dev/ttyUSB0',
        baud=921600,
        erase_nvs=True,
        esptool='',
        force_no_stub=False,
        check_no_stub=False,
    )


def _partition_bin_fixture(tmp_path: Path) -> Tuple[Path, Path]:
    """Create a minimal ParseBinPath tree with one nvs partition bin.

    Returns:
        (bin_dir, part_bin)
    """
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'flasher_args.json').write_text(
        '{"write_flash_args": ["--flash_mode", "dio", "--flash_size", "2MB", "--flash_freq", "40m"], '
        '"flash_files": {}, '
        '"extra_esptool_args": {"chip": "esp32", "stub": true, '
        '"before": "default_reset", "after": "hard_reset"}}',
        encoding='utf-8',
    )
    (bin_dir / 'bootloader').mkdir()
    (bin_dir / 'partition_table').mkdir()
    (bin_dir / 'partition_table' / 'partition-table.csv').write_text('nvs,data,nvs,0x9000,24K,\n', encoding='utf-8')
    part_bin = tmp_path / 'nvs.bin'
    part_bin.write_bytes(b'\xaa' * 128)
    return bin_dir, part_bin


@mock.patch.object(download_bin_module, 'compute_serial_port', return_value='/dev/ttyUSB0')
@mock.patch.object(download_bin_module.subprocess, 'run')
def test_download_partition_success(mock_run: mock.MagicMock, _mock_port: mock.MagicMock, tmp_path: Path) -> None:
    """download_partition 在 esptool 成功时应直接返回。"""
    bin_dir, part_bin = _partition_bin_fixture(tmp_path)

    mock_completed = mock.MagicMock()
    mock_completed.returncode = 0
    mock_completed.stdout = ''
    mock_completed.stderr = ''
    mock_run.return_value = mock_completed

    download_bin_module._get_bin_parser.cache_clear()
    try:
        tool = DownBinTool(str(bin_dir), '/dev/ttyUSB0', baud=115200, esptool='python -m esptool')
        tool.download_partition({'nvs': str(part_bin)})
    finally:
        download_bin_module._get_bin_parser.cache_clear()

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert 'write_flash' in call_args
    assert '/dev/ttyUSB0' in call_args
    assert '115200' in call_args
    assert str(part_bin) in call_args


@mock.patch.object(download_bin_module, 'compute_serial_port', return_value='/dev/ttyUSB0')
@mock.patch.object(download_bin_module.subprocess, 'run')
def test_download_partition_failure_raises_runtime_error(
    mock_run: mock.MagicMock, _mock_port: mock.MagicMock, tmp_path: Path
) -> None:
    """esptool 非零退出码时应抛出 RuntimeError（失败分支需正确拼接日志）。"""
    bin_dir, part_bin = _partition_bin_fixture(tmp_path)

    mock_completed = mock.MagicMock()
    mock_completed.returncode = 2
    mock_completed.stdout = 'stub output\n'
    mock_completed.stderr = 'err line\n'
    mock_run.return_value = mock_completed

    download_bin_module._get_bin_parser.cache_clear()
    try:
        tool = DownBinTool(str(bin_dir), '/dev/ttyUSB0', baud=115200, esptool='python -m esptool')
        with pytest.raises(RuntimeError, match='Failed to download partitions'):
            tool.download_partition({'nvs': str(part_bin)})
    finally:
        download_bin_module._get_bin_parser.cache_clear()


@mock.patch.object(download_bin_module, 'compute_serial_port', return_value='/dev/ttyUSB0')
@mock.patch.object(download_bin_module.subprocess, 'run')
def test_download_partition_explicit_baud_overrides_tool_baud(
    mock_run: mock.MagicMock, _mock_port: mock.MagicMock, tmp_path: Path
) -> None:
    """显式 baud 应覆盖 DownBinTool 构造时的 baud_list。"""
    bin_dir, part_bin = _partition_bin_fixture(tmp_path)

    mock_completed = mock.MagicMock()
    mock_completed.returncode = 0
    mock_completed.stdout = ''
    mock_completed.stderr = ''
    mock_run.return_value = mock_completed

    download_bin_module._get_bin_parser.cache_clear()
    try:
        tool = DownBinTool(str(bin_dir), '/dev/ttyUSB0', baud=115200, esptool='python -m esptool')
        tool.download_partition({'nvs': str(part_bin)}, baud=460800)
    finally:
        download_bin_module._get_bin_parser.cache_clear()

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert '460800' in call_args
    assert '115200' not in call_args


@mock.patch.object(download_bin_module, 'compute_serial_port', return_value='/dev/ttyUSB0')
@mock.patch.object(download_bin_module.subprocess, 'run')
def test_download_partition_retries_baud_list_on_failure(
    mock_run: mock.MagicMock, _mock_port: mock.MagicMock, tmp_path: Path
) -> None:
    """baud 列表中前一次失败时应继续尝试下一个 baud，且 args 不累积。"""
    bin_dir, part_bin = _partition_bin_fixture(tmp_path)

    fail = mock.MagicMock(returncode=1, stdout='fail\n', stderr='')
    ok = mock.MagicMock(returncode=0, stdout='', stderr='')
    mock_run.side_effect = [fail, ok]

    download_bin_module._get_bin_parser.cache_clear()
    try:
        tool = DownBinTool(str(bin_dir), '/dev/ttyUSB0', baud=115200, esptool='python -m esptool')
        tool.download_partition({'nvs': str(part_bin)}, baud=[921600, 460800])
    finally:
        download_bin_module._get_bin_parser.cache_clear()

    assert mock_run.call_count == 2
    first_args = mock_run.call_args_list[0][0][0]
    second_args = mock_run.call_args_list[1][0][0]
    assert first_args.count('-b') == 1
    assert second_args.count('-b') == 1
    assert '921600' in first_args
    assert '460800' in second_args
    assert '921600' not in second_args


@mock.patch.object(download_bin_module, 'compute_serial_port', return_value='/dev/ttyUSB0')
@mock.patch.object(download_bin_module.subprocess, 'run')
def test_download_partition_all_bauds_fail_raises(
    mock_run: mock.MagicMock, _mock_port: mock.MagicMock, tmp_path: Path
) -> None:
    """baud 列表全部失败后应抛出 RuntimeError。"""
    bin_dir, part_bin = _partition_bin_fixture(tmp_path)

    mock_run.return_value = mock.MagicMock(returncode=2, stdout='out\n', stderr='err\n')

    download_bin_module._get_bin_parser.cache_clear()
    try:
        tool = DownBinTool(str(bin_dir), '/dev/ttyUSB0', baud=115200, esptool='python -m esptool')
        with pytest.raises(RuntimeError, match='Failed to download partitions'):
            tool.download_partition({'nvs': str(part_bin)}, baud=[921600, 460800])
    finally:
        download_bin_module._get_bin_parser.cache_clear()

    assert mock_run.call_count == 2


def test_download_bin_reexports_bin_path_to_dir() -> None:
    """download_bin 模块应继续暴露 bin_path_to_dir，且与 parse_bin_path 中实现为同一对象。"""
    assert download_bin_module.bin_path_to_dir is bin_path_to_dir_canonical
