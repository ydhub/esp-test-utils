from unittest import mock

import esptest.tools.download_bin as download_bin_module
from esptest.tools.download_bin import BinConfig, download_bin_to_ports, download_bins


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
        bin_path, '/dev/ttyUSB0', erase_nvs=True, force_no_stub=False, check_no_stub=False
    )
    mock_down_bin_tool.assert_any_call(
        bin_path, '/dev/ttyUSB1', erase_nvs=True, force_no_stub=False, check_no_stub=False
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
        '/path/to/bin1', '/dev/ttyUSB0', erase_nvs=True, force_no_stub=False, check_no_stub=False
    )
    mock_down_bin_tool.assert_any_call(
        '/path/to/bin2', '/dev/ttyUSB1', erase_nvs=False, force_no_stub=False, check_no_stub=False
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
        '/bin/path', '/dev/ttyUSB0', erase_nvs=True, force_no_stub=False, check_no_stub=False
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
        '/path/bin', '/dev/ttyUSB0', erase_nvs=False, force_no_stub=True, check_no_stub=True
    )
    mock_down_bin_tool.return_value.download.assert_called_once()
