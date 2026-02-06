import contextlib
import io
import time
import warnings
from functools import wraps

import esptest.common.compat_typing as t

from ..logger import get_logger

logger = get_logger('basic')

# From python 3.10 this could be more succinct
# https://docs.python.org/3/library/typing.html#typing.ParamSpec
GenericFunc = t.TypeVar('GenericFunc', bound=t.Callable[..., t.Any])


def enhance_import_error_message(message: str) -> t.Callable[[GenericFunc], GenericFunc]:
    """Decorator that enriches ImportError with function name and custom message.

    When the decorated function raises an ImportError, the exception message
    is appended with `` from {func.__name__}: {message}`` to aid fixing.

    Args:
        message (str): Extra hint to append to the ImportError message.

    Returns:
        t.Callable[[GenericFunc], GenericFunc]: A decorator for the target function.
    """

    def decorator(func: GenericFunc) -> GenericFunc:
        @wraps(func)
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            try:
                return func(*args, **kwargs)
            except ImportError as e:
                e.msg += f' from {func.__name__}: {message}'
                raise

        return t.cast(GenericFunc, wrapper)

    return decorator


class _NotUsedException(UserWarning):
    pass


def retry(
    max_retry: int = 3,
    on_result: t.Union[t.List[t.Any], t.Callable[[t.Any], bool]] = lambda x: False,
    on_exception: t.Tuple[t.Type[Exception], ...] = (_NotUsedException,),
    delay: float = 0,
) -> t.Callable[[GenericFunc], GenericFunc]:
    """Retry decorator

    The decorated function is called at most ``max_retry`` times. A retry happens when:
    - The return value fails the ``on_result`` check (if configured), or
    - An exception matching ``on_exception`` is raised (if configured).

    **on_result** controls retry based on return value. It can be:
    - **list**: Retry when the return value is **not** in the list; stop and return when it is in the list.
    - **callable**: Retry when the callable returns True (result unacceptable); stop and return when it returns False.
    Default is a callable that always returns False, so no retry based on result.

    **on_exception** limits which exceptions trigger a retry. Only exceptions whose type is in this tuple
    are caught and cause a retry; others are re-raised. Default uses an internal sentinel so no retry on exception.

    Args:
        max_retry: Maximum number of total calls. Defaults to 3.
        on_result: Retry based on return value, see description above. Default: no retry on result.
        on_exception: Retry when one of these exceptions is raised. Default: no exception handled.
        delay: Delay before next retry. Defaults to 0.

    Returns:
        t.Callable[[GenericFunc], GenericFunc]: A decorator for the target function.
    """

    def decorator(func: GenericFunc) -> GenericFunc:
        @wraps(func)
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            for _ in range(max_retry - 1):
                try:
                    ret = func(*args, **kwargs)
                    if isinstance(on_result, list):
                        if ret not in on_result:
                            return ret
                    else:
                        assert isinstance(on_result, t.Callable)  # type: ignore
                        if not on_result(ret):
                            return ret
                    logger.info(f'Func {func.__name__} returns {ret}, retrying ...')
                except on_exception as e:
                    logger.info(f'Func {func.__name__} {type(e)}: {str(e)}, retrying ...')
                if delay:
                    time.sleep(delay)
            # Last retry
            return func(*args, **kwargs)

        return t.cast(GenericFunc, wrapper)

    return decorator


def deprecated(reason: str = '') -> t.Callable[[GenericFunc], GenericFunc]:
    """Show deprecated message when method is called"""

    def decorator(func: GenericFunc) -> GenericFunc:
        @wraps(func)
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            with warnings.catch_warnings():
                warnings.simplefilter('once', DeprecationWarning)
                warnings.warn(reason, category=DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        return t.cast(GenericFunc, wrapper)

    return decorator


def suppress_stdout() -> t.Callable[[GenericFunc], GenericFunc]:
    """Redirect stdout and stderr to discard output during the decorated function's execution."""

    def decorator(func: GenericFunc) -> GenericFunc:
        @wraps(func)
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            devnull = io.StringIO()
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                return func(*args, **kwargs)

        return t.cast(GenericFunc, wrapper)

    return decorator


def timeit(
    print_func: t.Callable[[str], None] = logger.critical,
    format_str: str = 'Func {func_name} time used: {time_used:.2f} s',
) -> t.Callable[[GenericFunc], GenericFunc]:
    """Show time used after method is called.

    After the function returns, ``print_func`` is called with the formatted string
    (supports ``{func_name}`` and ``{time_used}`` placeholders).

    Args:
        print_func callable[[str], None]: Callable to output the timing message. Defaults to logger.critical.
        format_str str: Format string for the message. Defaults to 'Func {func_name} time used: {time_used:.2f} s'.

    Returns:
        t.Callable[[GenericFunc], GenericFunc]: A decorator for the target function.
    """

    def decorator(func: GenericFunc) -> GenericFunc:
        @wraps(func)
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            start_time = time.perf_counter()
            ret = func(*args, **kwargs)
            end_time = time.perf_counter()
            print_func(format_str.format(func_name=func.__name__, time_used=end_time - start_time))
            return ret

        return t.cast(GenericFunc, wrapper)

    return decorator
