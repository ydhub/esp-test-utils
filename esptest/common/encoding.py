from typing import Optional, Union


def to_str(data: Union[str, bytes], encoding: str = 'utf-8', errors: str = 'replace') -> str:
    """Turn `bytes` or `str` to `str`

    Args:
        data (AnyStr): input `bytes` or `str` data
        encoding (str, optional): The encoding with which to decode the bytes. Defaults to 'utf-8'.
        errors (str, optional): The error handling scheme to use for the handling of decoding errors.

    Returns:
        str: utf8-decoded string
    """
    if isinstance(data, bytes):
        return data.decode(encoding, errors=errors)
    return data


def to_bytes(data: Union[str, bytes], ending: Optional[Union[str, bytes]] = None, encoding: str = 'utf-8') -> bytes:
    """Turn `bytes` or `str` to `bytes`

    Args:
        data (AnyStr): input `bytes` or `str` data
        ending (Optional[AnyStr], optional): add encoded given ending to the end of data. Defaults to None.
        encoding (str, optional): The encoding with which to encode the string. Defaults to 'utf-8'.

    Returns:
        bytes: utf8-encoded bytes
    """
    if isinstance(data, str):
        data = data.encode(encoding=encoding)
    if ending:
        if isinstance(ending, str):
            ending = ending.encode(encoding=encoding)
        return data + ending
    return data
