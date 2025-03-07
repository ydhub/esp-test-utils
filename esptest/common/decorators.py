import time
import warnings
from functools import wraps
from typing import Any, Callable, List, Tuple, Type, TypeVar, Union, cast

from ..logger import get_logger

logger = get_logger('basic')

# From python 3.10 this could be more succinct
# https://docs.python.org/3/library/typing.html#typing.ParamSpec
GenericFunc = TypeVar('GenericFunc', bound=Callable[..., Any])


def enhance_import_error_message(message: str) -> Callable[[GenericFunc], GenericFunc]:
    def decorator(func: GenericFunc) -> GenericFunc:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except ImportError as e:
                e.msg += f' from {func.__name__}: {message}'
                raise

        return cast(GenericFunc, wrapper)

    return decorator


class _NotUsedException(UserWarning):
    pass


def retry(
    max_retry: int = 3,
    on_result: Union[List[Any], Callable[[Any], bool]] = lambda x: False,
    on_exception: Tuple[Type[Exception], ...] = (_NotUsedException,),
    delay: float = 0,
) -> Callable[[GenericFunc], GenericFunc]:
    """Retry decorator

    For parameter "on_result", it can be a list or a callable.


    Args:
        max_retry (int, optional): Max retry count. Defaults to 3.
        on_result (Union[List[Any], Callable[[Any], bool]], optional): Retry if the result if not expected.
        on_exception (Tuple[Type[Exception], ...], optional): Retry if exception, do not handle exception by default.
        delay (float, optional): Delay before next retry. Defaults to 0.

    Returns:
        Callable[[GenericFunc], GenericFunc]: decorator
    """

    def decorator(func: GenericFunc) -> GenericFunc:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for _ in range(max_retry - 1):
                try:
                    ret = func(*args, **kwargs)
                    if isinstance(on_result, list):
                        if ret not in on_result:
                            return ret
                    else:
                        assert isinstance(on_result, Callable)  # type: ignore
                        if not on_result(ret):
                            return ret
                    logger.info(f'Func {func.__name__} returns {ret}, retrying ...')
                except on_exception as e:
                    logger.info(f'Func {func.__name__} {type(e)}: {str(e)}, retrying ...')
                if delay:
                    time.sleep(delay)
            # Last retry
            return func(*args, **kwargs)

        return cast(GenericFunc, wrapper)

    return decorator


def deprecated(reason: str = '') -> Callable[[GenericFunc], GenericFunc]:
    """Show deprecated message when method is called"""

    def decorator(func: GenericFunc) -> GenericFunc:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with warnings.catch_warnings():
                warnings.simplefilter('once', DeprecationWarning)
                warnings.warn(reason, category=DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        return cast(GenericFunc, wrapper)

    return decorator
