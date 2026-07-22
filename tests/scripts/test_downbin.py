from unittest import mock

from esptest.scripts import downbin


def test_main_passes_baudrate_to_download_bin_to_ports() -> None:
    # fmt: off
    with mock.patch.object(downbin.os.path, 'isdir', return_value=True), \
        mock.patch.object(downbin.sys, 'argv', ['downbin', '/path/to/bin', '-p', 'P0', '--baudrate', '115200']), \
        mock.patch.object(downbin, 'download_bin_to_ports') as download_bin_to_ports:
        downbin.main()
    # fmt: on

    download_bin_to_ports.assert_called_once_with(
        '/path/to/bin',
        ['P0'],
        True,
        max_workers=0,
        force_no_stub=False,
        check_no_stub=False,
        baud=115200,
    )


def test_main_merged_resolves_bin_path_with_allow_merged() -> None:
    resolved = '/tmp/resolved_merged.bin'
    # fmt: off
    with mock.patch.object(
        downbin.sys,
        'argv',
        ['downbin', '/tmp/firmware.bin', '--merged', '-p', 'P0'],
    ), \
        mock.patch.object(downbin, 'bin_path_to_dir_or_bin', return_value=resolved) as resolve_merged, \
        mock.patch.object(downbin, 'bin_path_to_dir') as resolve_dir, \
        mock.patch.object(downbin, 'download_bin_to_ports') as download_bin_to_ports:
        downbin.main()
    # fmt: on

    resolve_merged.assert_called_once_with('/tmp/firmware.bin', allow_merged=True, check_valid=True)
    resolve_dir.assert_not_called()
    download_bin_to_ports.assert_called_once_with(
        resolved,
        ['P0'],
        False,  # --merged forces erase_nvs=False
        max_workers=0,
        force_no_stub=False,
        check_no_stub=False,
        baud=0,
    )
