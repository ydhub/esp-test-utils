from datetime import datetime
from typing import Optional


def generate_timestamp(fmt: str = '%Y-%m-%d %H:%M:%S.%f', dt: Optional[datetime] = None) -> str:
    """Generates a timestamp string from datetime

    Args:
        fmt (str, optional): time stamp format. Defaults to '%Y-%m-%d %H:%M:%S.%f', follow ISO 8601 Formats.
        dt (datetime, optional): convert specific datetime to string. Defaults to datatime.now().

    Returns:
        str: _description_
    """
    if not dt:
        dt = datetime.now()
    return dt.strftime(fmt)
