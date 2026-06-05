from unittest.mock import patch

from esptest.devices import tempbox


def test_get_tempbox_port_uses_compute_when_port_is_given() -> None:
    with patch.object(tempbox, 'compute_serial_port', return_value='/dev/ttyUSB1') as mock_compute:
        assert tempbox.get_tempbox_port('/dev/ttyUSBx') == '/dev/ttyUSB1'

    mock_compute.assert_called_once_with('/dev/ttyUSBx', strict=False)


def test_start_program_test_writes_registers_in_order() -> None:
    with patch.object(tempbox.serial, 'Serial'):
        controller = tempbox.TempboxController(port='/dev/ttyUSB1', address=1)

    with patch.object(controller, 'write_single_register') as mock_write:
        controller.start_program_test(program_no=7)

    assert mock_write.call_args_list == [
        (('D0090', 0), {}),
        (('D0062', 7), {}),
        (('D0063', 1), {}),
    ]


def test_stop_current_job_writes_stop_command() -> None:
    with patch.object(tempbox.serial, 'Serial'):
        controller = tempbox.TempboxController(port='/dev/ttyUSB1', address=1)

    with patch.object(controller, 'write_single_register') as mock_write:
        controller.stop_current_job()

    mock_write.assert_called_once_with('D0063', 0)
