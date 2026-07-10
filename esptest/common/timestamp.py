from datetime import datetime

import esptest.common.compat_typing as t


def timestamp_str(fmt: str = '', dt: t.Optional[datetime] = None) -> str:
    """Generates a timestamp string from datetime

    Args:
        fmt (str, optional): time stamp format. Defaults to '%Y-%m-%dT%H:%M:%S.%f', follow ISO 8601 Formats.
        dt (datetime, optional): convert specific datetime to string. Defaults to datatime.now().

    Returns:
        str: time stamp string
    """
    if not fmt:
        fmt = '%Y-%m-%dT%H:%M:%S.%f'
    if not dt:
        dt = datetime.now()
    if dt.tzinfo is None:
        # Attach the local timezone so the output carries an explicit offset.
        dt = dt.astimezone()
    return dt.strftime(fmt)


def timestamp_iso(dt: t.Optional[datetime] = None) -> str:
    """Generates a timezone-aware ISO 8601 timestamp string.

    Unlike timestamp_str, the result always includes a timezone offset,
    e.g. '2026-07-08T12:32:00.123456+0800'.

    Args:
        dt (datetime, optional): datetime to convert. Naive datetimes are
            assumed to be in the local timezone. Defaults to datetime.now().

    Returns:
        str: ISO 8601 timestamp string with microseconds and timezone offset
    """
    return timestamp_str(fmt='%Y-%m-%dT%H:%M:%S.%f%z', dt=dt)


# Candidate formats tried (in order) when no explicit fmt is given.
# Timezone-aware variants come first so an offset is preserved when present;
# %z accepts '+0800', '+08:00' and 'Z' since Python 3.7.
_PARSE_FORMATS = (
    '%Y-%m-%dT%H:%M:%S.%f%z',
    '%Y-%m-%dT%H:%M:%S%z',
    '%Y-%m-%dT%H:%M:%S.%f',
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%d %H:%M:%S.%f%z',
    '%Y-%m-%d %H:%M:%S%z',
    '%Y-%m-%d %H:%M:%S.%f',
    '%Y-%m-%d %H:%M:%S',
)


def parse_timestamp(text: str, fmt: str = '') -> datetime:
    """Parses a timestamp string into a datetime.

    Inverse of timestamp_str. When ``fmt`` is omitted, a set of common
    formats is tried automatically, covering both ``T`` and space separators,
    with or without microseconds, and with or without a timezone offset
    (``+0800``, ``+08:00`` or ``Z``). Timezone-aware candidates are tried
    first, so the offset is preserved whenever the input carries one.

    Args:
        text (str): the timestamp string to parse.
        fmt (str, optional): explicit strptime format. When given, only this
            format is used. Defaults to auto-detection.

    Returns:
        datetime: the parsed datetime object.

    Raises:
        ValueError: if the string does not match any known format.
    """
    if fmt:
        return datetime.strptime(text, fmt)
    for candidate in _PARSE_FORMATS:
        try:
            return datetime.strptime(text, candidate)
        except ValueError:
            continue
    raise ValueError(f'Unrecognized timestamp format: {text!r}')


def timestamp_slug(fmt: str = '', dt: t.Optional[datetime] = None) -> str:
    """Similar to timestamp_str but only include ``[0-9a-zA-Z_-]``.

    Returns:
        str: time stamp string
    """
    s = timestamp_str(fmt, dt)
    s = s.replace(':', '-').replace(' ', '__').replace('.', '_')
    return s
