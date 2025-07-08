from datetime import datetime

import esptest.common.compat_typing as t


def timestamp_str(fmt: str = '', dt: t.Optional[datetime] = None) -> str:
    """Generates a timestamp string from datetime

    Args:
        fmt (str, optional): time stamp format. Defaults to '%Y-%m-%d %H:%M:%S.%f', follow ISO 8601 Formats.
        dt (datetime, optional): convert specific datetime to string. Defaults to datatime.now().

    Returns:
        str: time stamp string
    """
    if not fmt:
        fmt = '%Y-%m-%d %H:%M:%S.%f'
    if not dt:
        dt = datetime.now()
    return dt.strftime(fmt)


def timestamp_slug(fmt: str = '', dt: t.Optional[datetime] = None) -> str:
    """Similar to timestamp_str but only include [0-9a-zA-Z_-]

    Returns:
        str: time stamp string
    """
    s = timestamp_str(fmt, dt)
    s = s.replace(':', '-').replace(' ', '__').replace('.', '_')
    return s
