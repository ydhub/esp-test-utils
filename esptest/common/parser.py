import os
import re
import string
from functools import lru_cache
from typing import Mapping, Match

import esptest.common.compat_typing as t

from ..logger import get_logger

logger = get_logger(__name__)

_ENV_VAR_PATTERN = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


@lru_cache()
def _log_env_var_replacement_once(var_name: str, value: str) -> None:
    logger.info(f'Replace environment variable `{var_name}` -> `{value}`')


def expand_env_vars(data: str, env: t.Optional[Mapping[str, str]] = None) -> str:
    """Expand environment variables in ``${VAR_NAME}`` form.

    Only braced environment variables are expanded. Missing variables raise
    ``KeyError`` from the selected environment mapping.
    """
    env_vars = os.environ if env is None else env

    def replace(match: Match[str]) -> str:
        var_name = match.group(1)
        if var_name in env_vars:
            value = env_vars[var_name]
            _log_env_var_replacement_once(var_name, value)
            return value
        raise KeyError(f'Environment variable `{var_name}` is not defined')

    return _ENV_VAR_PATTERN.sub(replace, data)


def _optional_int(value: t.Optional[str]) -> t.Optional[int]:
    """Convert a string to ``int``; return ``None`` for ``None`` or empty string.

    Used to parse omissible fields inside slice expressions.
    """
    return int(value) if value not in (None, '') else None  # type: ignore


def _require_max_len(max_len: t.Optional[int], part: str) -> int:
    if max_len is None or max_len <= 0:
        raise ValueError(f'`max_len` is required for slice `{part}`')
    return max_len


def get_zfill_len(data: str, force: bool = False) -> int:
    """Resolve the zero-fill width for the given expression.

    - If the expression ends with ``#<N>``, return ``N`` (explicitly declared width).
    - Otherwise, when ``force=True``, return the length of the longest numeric run
      found in the expression.
    - Return ``0`` in all other cases (no zero-fill).

    Examples:
        "2-7#3"  -> 3
        "02-07"  -> 2  (force=True)
        "1,2"    -> 0
    """
    m = re.search(r'#(\d+)$', data)
    if m:
        return int(m.group(1))
    if force:
        return max(map(len, re.findall(r'\d+', data)))
    return 0


def _expand_to_list_ex(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    data: str,
    max_len: t.Optional[int] = None,
    sort: bool = False,
    dedup: bool = False,
    zfilled: bool = False,
    is_index: bool = False,
    strip: bool = False,
    valid_chars: str = '',
) -> t.List[t.Union[int, str]]:
    """Expand a compact expression into a list (low-level implementation).

    Prefer using :func:`expand_to_list` or :func:`parse_param_idx` from the outside.

    Supported syntax (``,`` is the separator; an optional ``#N`` suffix declares the
    zero-fill width):

    - Single point:    ``3``                  -> [3]
    - Range:           ``2-5``                -> [2, 3, 4, 5]
    - Python slice:    ``start:[stop[:step]]``, semantics align with list slicing
                       (e.g. ``1:-1``, ``::-1``)
    - Exclusion:       ``!<expr>``            remove the expansion of ``<expr>``
                       from the current result set
    - Composition:     ``0,2-7,!5``           -> [0, 2, 3, 4, 6, 7]
    - Zero-fill:       ``2-7#3``              -> ['002', ..., '007']
    - String list:     ``a,b,c``              -> ['a', 'b', 'c'] (``is_index=False``)

    Args:
        data: The expression to parse. Empty string or ``None`` is treated as invalid.
        max_len: Total length of the target sequence. Required only when the slice or
            negative indexing depends on it.
        sort: Whether to sort the final result in ascending order.
        dedup: Whether to de-duplicate the final result (implemented via ``set``,
            which does not preserve input order).
        zfilled: Whether to force zero-fill the output to the longest numeric width
            (and emit strings).
        is_index: Whether to parse with index semantics (enables slice, negative index
            and ``!`` exclusion).
        strip: Whether to ``strip()`` whitespace around each comma-separated segment.
        valid_chars: Character whitelist for segments that may be preserved as raw
            string tokens.

    Returns:
        The parsed list; elements may be ``int`` or ``str`` depending on whether
        zero-fill or string-token handling was triggered.

    Raises:
        ValueError: If the input is empty, the format is invalid, or a slice requires
            ``max_len`` but none was supplied.
    """
    if not data:
        raise ValueError('Invalid input')

    # Parse the zero-fill width, then strip the `#N` suffix.
    zfill_len = get_zfill_len(data, zfilled)
    data = data.split('#')[0]

    all_idx: t.List[int] = []
    if is_index:
        # Pre-build the full index pool; filled only when max_len is given, and
        # consulted on demand during slice evaluation.
        all_idx = list(range(max_len)) if max_len else []
        # Backward compatibility: accept `/` as an alternative separator.
        data = data.replace('/', ',')

    parse_results: t.List[t.Union[int, str]] = []
    for part in data.split(','):
        if strip:
            part = part.strip()

        if not part:
            raise ValueError('format error: empty segment')

        # `!` exclusion: valid only in index mode; drop the expansion of the
        # sub-expression from the current result set.
        if part.startswith('!'):
            if not is_index:
                raise ValueError(f'format error: `!` exclusion is only valid in index mode (`{part}`)')
            # When nothing has been accumulated yet, fall back to the full index
            # pool so that pure `!xxx` expressions still work.
            parse_results = parse_results or list(all_idx)
            excluded = _expand_to_list_ex(part[1:], max_len, is_index=is_index)
            parse_results = [i for i in parse_results if i not in excluded]
            continue

        # String token: keep the segment as-is only if every character is in the
        # `valid_chars` whitelist.
        if valid_chars and all(char in valid_chars for char in part):
            parse_results.append(part)
            continue

        if is_index and part.isdigit():
            parse_results.append(int(part))
            continue

        # Range: `<start>-<end>`, non-negative integers on both sides, inclusive.
        match = re.match(r'^(\d+)-(\d+)$', part)
        if match:
            start, end = map(int, match.groups())
            new_values = range(start, end + 1) if is_index else list(map(str, range(start, end + 1)))
            parse_results.extend(new_values)
            continue

        if is_index:
            # Python slice: `start:[stop[:step]]`; each field may be empty or negative.
            match = re.match(r'^(?P<start>-?\d*):(?P<stop>-?\d*)(:(?P<step>-?\d*))?$', part)
            if match:
                start, stop, step = map(_optional_int, match.groupdict().values())  # type: ignore
                if step is None:
                    step = 1
                if step == 0:
                    raise ValueError(f'Invalid slice format `{part}`, step cannot be 0')
                # For step > 0 the business rule clamps a negative `start` to 0;
                # other cases follow Python slice semantics.
                if start is None:
                    start = 0 if step > 0 else _require_max_len(max_len, part) - 1
                elif start < 0:
                    start = 0 if step > 0 else max(0, _require_max_len(max_len, part) + start)
                if stop is None:
                    stop = _require_max_len(max_len, part) if step > 0 else -1
                elif stop < 0:
                    stop = _require_max_len(max_len, part) + stop

                new_values = range(start, stop, step) if is_index else list(map(str, range(start, stop, step)))
                parse_results.extend(new_values)
                continue
            if ':' in part:
                raise ValueError(f'Invalid slice format `{part}`, use `start:[stop[:step]]`')

        raise ValueError(f'format error: unrecognized segment `{part}`')

    # Normalize to int in index mode to avoid mixing string tokens with numbers.
    if is_index:
        int_results: t.List[int] = [int(x) for x in parse_results]
        if max_len is not None and any(x < 0 or x >= max_len for x in int_results):
            raise ValueError(f'index out of range, max_len={max_len}')
        parse_results = list(int_results)

    if dedup:
        parse_results = list(set(parse_results))
    if sort:
        parse_results.sort()  # type: ignore[call-overload]
    if zfill_len:
        parse_results = [str(item).zfill(zfill_len) for item in parse_results]

    return parse_results


def expand_to_list(
    data: str,
    valid_chars: str = '',
) -> t.List[str]:
    """Expand a string expression into a list of tokens (string mode).

    Index / slice / ``!`` exclusion semantics are not enabled in this mode.

    The default ``valid_chars`` is ``letters + digits + whitespace``; a comma-
    separated segment is kept as a raw string token only if every one of its
    characters falls inside this set.

    Args:
        data: The expression to parse.
        valid_chars: Character whitelist for raw string tokens; the default set is
            used when this is empty.

    Returns:
        A list of string tokens.

    Examples:
        "a,b,c"    -> ['a', 'b', 'c']
        "a1,b2"    -> ['a1', 'b2']
        "2-5"      -> [2, 3, 4, 5]   # range syntax still applies
    """
    if not valid_chars:
        valid_chars = string.digits + string.ascii_letters + string.whitespace
    expended = _expand_to_list_ex(data, is_index=False, valid_chars=valid_chars)
    if len(expended) <= 1:
        raise ValueError(f'format error: invalid expression `{data}`')
    # In string mode `_expand_to_list_ex` only ever appends strings, so the cast is safe.
    return [str(x) for x in expended]


def parse_param_idx(
    data: str,
    max_len: t.Optional[int] = None,
    sort: bool = False,
    dedup: bool = False,
    zfilled: bool = False,
) -> t.List[t.Union[int, str]]:
    """Expand a parameter-index expression into an index list (index mode).

    Supports Python-style slices, negative indices and ``!`` exclusion. Equivalent
    to ``_expand_to_list_ex(data, ..., is_index=True, strip=True)``.

    Args:
        data: The index expression, e.g. ``'0,2-7,!5'``, ``'::-1'``, ``'02-07'``.
        max_len: Total length of the target sequence; required when the expression
            contains open-ended slices or negative indices.
        sort: Whether to sort the result in ascending order.
        dedup: Whether to de-duplicate the result (does not preserve order).
        zfilled: Whether to zero-fill the output to the longest numeric width and
            emit strings; the element type becomes ``str`` only in this case.

    Returns:
        ``List[int]`` when ``zfilled=False``; ``List[str]`` when ``zfilled=True``.

    Examples (max_len=10):
        "3:,11-14"  -> [3, 4, 5, 6, 7, 8, 9]
        "4::-1"     -> [4, 3, 2, 1, 0]
        "0,2-7,!5"  -> [0, 2, 3, 4, 6, 7]
        "!3,!7"     -> [0, 1, 2, 4, 5, 6, 8, 9]
        "!3-7"      -> [0, 1, 2, 8, 9]
        "02-07"     -> ['02', '03', '04', '05', '06', '07']  (zfilled=True)
        "2-7#3"     -> ['002', '003', '004', '005', '006', '007']
    """
    return _expand_to_list_ex(
        data,
        max_len=max_len,
        sort=sort,
        dedup=dedup,
        zfilled=zfilled,
        is_index=True,
        strip=True,
    )
