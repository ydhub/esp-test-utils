import inspect
import sys


def test_import_from_all() -> None:
    if 'esptest' in sys.modules:
        del sys.modules['esptest']

    # exported methods / classes
    from esptest.all import DutBase, DutConfig, EspDut, SerialPort, dut_wrapper, get_logger, run_cmd, to_bytes, to_str

    # pass ruff format
    assert all(callable(fn) for fn in [dut_wrapper, to_bytes, to_str, run_cmd, get_logger])
    assert all(inspect.isclass(cls) for cls in [DutBase, DutConfig, EspDut, SerialPort])
