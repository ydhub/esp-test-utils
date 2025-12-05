import io
import time
from contextlib import redirect_stdout

import pytest

from esptest.common.decorators import retry, timeit


def test_retry_on_result() -> None:
    test_var = 0

    @retry(3, on_result=[0, 1, 4])
    def test_func1() -> int:
        nonlocal test_var
        test_var += 1
        return test_var

    # Test retry and succeeded
    t0 = time.time()
    ret = test_func1()
    assert time.time() - t0 < 0.1
    assert ret == 2

    @retry(3, on_result=[0, 1, 2, 3, 4])
    def test_func2() -> int:
        nonlocal test_var
        test_var += 1
        return test_var

    # Test retry max exceeded
    test_var = 0
    t0 = time.time()
    ret = test_func2()
    assert time.time() - t0 < 0.1
    assert ret == 3

    @retry(3, on_result=[0, 1, 2, 4], delay=0.1)
    def test_func3() -> int:
        nonlocal test_var
        test_var += 1
        return test_var

    # Test retry with delay
    test_var = 0
    t0 = time.time()
    ret = test_func3()
    assert 0.1 < time.time() - t0 < 0.3
    assert ret == 3


def test_retry_if_except() -> None:
    test_var: int = 0

    @retry(5, on_exception=(ValueError,), delay=0.1)
    def test_func1() -> int:
        nonlocal test_var
        test_var += 1
        if test_var < 3:
            raise ValueError()
        return test_var

    # Test retry and succeeded
    t0 = time.time()
    ret = test_func1()
    assert 0.1 < time.time() - t0 < 0.3
    assert ret == 3

    @retry(3, on_exception=(ValueError,))
    def test_func2() -> int:
        nonlocal test_var
        test_var += 1
        if test_var < 5:
            raise ValueError()
        return test_var

    # Test max retry
    test_var = 0
    t0 = time.time()
    with pytest.raises(ValueError):
        _ = test_func2()
    assert time.time() - t0 < 0.1

    @retry(5, on_exception=(UserWarning,))
    def test_func3() -> int:
        nonlocal test_var
        test_var += 1
        if test_var < 3:
            raise ValueError()
        return test_var

    # Test exception not match
    test_var = 0
    t0 = time.time()
    with pytest.raises(ValueError):
        _ = test_func3()
    assert time.time() - t0 < 0.1


def test_timeit() -> None:
    @timeit(print_func=print)  # output to stdout using print
    def test_func1() -> None:
        pass

    @timeit(print_func=print, format_str='Func2 time used: {time_used:.1f} s')
    def test_func2() -> None:
        time.sleep(0.1)

    with redirect_stdout(io.StringIO()) as f:
        test_func1()
        out = f.getvalue().strip()
        assert 'Func test_func1 time used: 0.00 s' in out

    with redirect_stdout(io.StringIO()) as f1:
        f1.flush()
        test_func2()
        out = f1.getvalue().strip()
        assert 'Func2 time used: ' in out
        assert '0.1' in out


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
