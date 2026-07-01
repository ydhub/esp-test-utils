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
