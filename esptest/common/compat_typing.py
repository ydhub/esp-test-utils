# pylint: disable=unused-import
# flake8: noqa: F401
# ruff: noqa: F401
import sys
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    AnyStr,
    Callable,
    Dict,
    Generator,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Protocol,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

if sys.version_info >= (3, 9):
    from contextlib import AbstractContextManager as ContextManager
else:
    from typing import ContextManager


if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


if sys.version_info >= (3, 10):
    from typing import Annotated, TypeAlias
else:
    from typing_extensions import Annotated, TypeAlias
