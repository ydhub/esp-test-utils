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

    For parameter "on_result", it can be a list or a callable.


    Args:
        max_retry (int, optional): Max retry count. Defaults to 3.
        on_result (Union[List[t.Any], Callable[[Any], bool]], optional): Retry if the result if not expected.
        on_exception (Tuple[Type[Exception], ...], optional): Retry if exception, do not handle exception by default.
        delay (float, optional): Delay before next retry. Defaults to 0.

    Returns:
        t.Callable[[GenericFunc], GenericFunc]: decorator
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
    """Disable all stdout and stderr"""

    def decorator(func: GenericFunc) -> GenericFunc:
        @wraps(func)
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            with contextlib.redirect_stdout(io.StringIO()):
                return func(*args, **kwargs)

        return t.cast(GenericFunc, wrapper)

    return decorator
