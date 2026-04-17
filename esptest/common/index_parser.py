import re


def _optional_int(value: str | None) -> int | None:
    return int(value) if value not in (None, '') else None  # type: ignore


def _require_max_len(all_idx: list, group: str) -> int:
    # 只在真正需要长度时（末尾索引 / Python 环绕）才要求 max_len。
    if not all_idx:
        raise ValueError(f'`max_len` is required for slice `{group}`')
    return len(all_idx)


def get_zfill_len(list_index: str, force: bool = False) -> int:
    m = re.search(r'#(\d+)$', list_index)
    if m:
        return int(m.group(1))
    if force:
        return max(map(len, re.findall(r'\d+', list_index)))
    return 0


def parse_param_idx(
    list_index: str, max_len: int | None = None, sort: bool = False, dedup: bool = False, zfilled: bool = False
) -> list[int | str]:
    """
    split_char: `,`
    input (max_len=10)  =>  output (sorted)
        "" / None       =>  [0,1, ..., 9]
        "3:,11-14"      =>  [3,4, ..., 9]
        "4::-1"         =>  [4,3,2,1,0]
        "0,2-7,!5"      =>  [0,2,3,4,6,7]
        "!3,!7"         =>  [0,1,2,4,5,6,8,9]
        "!3-7"          =>  [0,1,2,8,9]
        "02-07"         =>  ['02','03','04','06','07']
        "2-7#3"         =>  ['002','003','004','006','007']
    """

    # get zfill length
    zfill_len = 0
    if list_index:
        zfill_len = get_zfill_len(list_index, zfilled)
        list_index = list_index.split('#')[0]

    # get all index
    add_idx: list[int | str] = []
    remove_idx = []
    all_idx = [] if bool(max_len) is False else list[int](range(max_len))  # type: ignore
    if bool(list_index) is False:
        list_index = ''  # empty string is valid
        if not all_idx:
            raise ValueError('`max_len` is required when list_index is empty')
    else:
        list_index = list_index.replace('/', ',')  # compliant with old version

    # parse param_idx
    for group in list_index.split(','):
        group = group.strip()
        # ignore empty string: ''
        if not group:
            pass

        # exclude index: `!7` / `!3-7`
        elif group.startswith('!'):
            remove_idx.extend(parse_param_idx(group[1:], max_len))

        # single index: `7`
        elif group.isdigit():
            add_idx.append(int(group))

        # range: `start-end`
        elif m := re.match(r'^(\d+)-(\d+)$', group):
            start, end = map(int, m.groups())
            add_idx.extend(range(start, end + 1))

        # slice format: `start:[stop[:step]]`
        elif m := re.match(r'^(?P<start>-?\d*):(?P<stop>-?\d*)(:(?P<step>-?\d*))?$', group):

            def optional_int(value: str | None) -> int | None:
                return int(value) if value not in (None, '') else None  # type: ignore

            start, stop, step = map(optional_int, m.groupdict().values())  # type: ignore

            # 只在真正需要长度时（末尾索引 / Python 环绕）才要求 max_len。
            def require_max_len() -> int:
                nonlocal all_idx, group
                if not all_idx:
                    raise ValueError(f'`max_len` is required for slice `{group}`')  # pylint: disable=W0640
                return len(all_idx)

            if step is None:
                step = 1
            elif step == 0:
                raise ValueError(f'Invalid slice format `{group}`, step cannot be 0')

            # step>0 时负 start 按业务语义钳到 0；其它情况（未写或负值）按 Python 切片语义处理。
            if start is None:
                start = 0 if step > 0 else require_max_len() - 1
            elif start < 0:
                start = 0 if step > 0 else max(0, require_max_len() + start)

            if stop is None:
                stop = require_max_len() if step > 0 else -1
            elif stop < 0:
                stop = require_max_len() + stop

            # 越界索引交给函数末尾 `idx in all_idx` 兜底过滤。
            add_idx.extend(range(start, stop, step))

        elif ':' in group:
            raise ValueError(f'Invalid slice format `{group}`, use `start:[stop[:step]]`')
        else:
            raise ValueError(f'Unknown index format: `{group}`')

    if not add_idx:
        add_idx = all_idx  # type: ignore
    elif all_idx:
        add_idx = [idx for idx in add_idx if idx in all_idx]

    # 从 add_idx 中删除所有在 remove_idx 中的索引
    add_idx = [idx for idx in add_idx if idx not in remove_idx]

    if dedup:  # 去重
        add_idx = list(set(add_idx))
    if sort:  # 排序
        add_idx.sort()
    if zfill_len:  # 填充前导0
        add_idx = [str(idx).zfill(zfill_len) for idx in add_idx]  # type: ignore
    return add_idx
