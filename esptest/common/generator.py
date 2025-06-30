from itertools import count


def get_next_index(owner: str = 'default') -> int:
    if not hasattr(get_next_index, 'cache'):
        get_next_index.cache = {}  # type: ignore
    if owner not in get_next_index.cache:  # type: ignore
        get_next_index.cache[owner] = count(start=1)  # type: ignore
    return next(get_next_index.cache[owner])  # type: ignore
