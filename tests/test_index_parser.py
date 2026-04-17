import pytest

from esptest.common.index_parser import parse_param_idx


@pytest.mark.parametrize(
    ('list_index', 'max_len', 'expected'),
    [
        ('', 10, list(range(10))),
        (None, 10, list(range(10))),
        ('', 1, [0]),
    ],
)
def test_parse_param_idx_empty_list_index(list_index: str, max_len: int, expected: list[int]) -> None:
    assert parse_param_idx(list_index, max_len) == expected


@pytest.mark.parametrize(
    ('list_index', 'max_len'),
    [
        ('', None),
        ('', 0),
    ],
)
def test_parse_param_idx_empty_list_index_requires_max_len(list_index: str, max_len: int) -> None:
    with pytest.raises(ValueError, match='max_len'):
        parse_param_idx(list_index, max_len)


def test_parse_param_idx_single_index() -> None:
    assert parse_param_idx('3', 10) == [3]


def test_parse_param_idx_range_and_exclusion() -> None:
    assert parse_param_idx('0,2-7,!5', 10) == [0, 2, 3, 4, 6, 7]


def test_parse_param_idx_bang_range_exclusion() -> None:
    assert parse_param_idx('2-5,!3-4', 10) == [2, 5]


def test_parse_param_idx_bang_exclusion_outside_added_range() -> None:
    assert parse_param_idx('0-4,!8', 10) == [0, 1, 2, 3, 4]


def test_parse_param_idx_bang_exclusion_after_explicit_full_range() -> None:
    assert parse_param_idx('0:,!3,!7', 10) == [0, 1, 2, 4, 5, 6, 8, 9]


# @pytest.mark.xfail(reason='pure ! exclusions do not initialize add_idx from all_idx')
def test_parse_param_idx_bang_only_points() -> None:
    assert parse_param_idx('!3,!7', 10) == [0, 1, 2, 4, 5, 6, 8, 9]


# @pytest.mark.xfail(reason='pure ! exclusions do not initialize add_idx from all_idx')
def test_parse_param_idx_bang_only_range() -> None:
    assert parse_param_idx('!3-7', 10) == [0, 1, 2, 8, 9]


def test_parse_param_idx_open_ended_slice_with_max_len() -> None:
    assert parse_param_idx('3:,11-14', 10) == [3, 4, 5, 6, 7, 8, 9]


def test_parse_param_idx_reverse_slice_with_max_len() -> None:
    assert parse_param_idx('::-1', 5) == [4, 3, 2, 1, 0]


def test_parse_param_idx_clamps_start_and_stop() -> None:
    assert parse_param_idx('-1:12', 10) == list(range(10))


def test_parse_param_idx_slice_negative_stop_is_not_empty_range() -> None:
    # 与 range(1, -1, 1)（空序列）不同，须为 list 切片语义 all_idx[1:-1]
    assert parse_param_idx('1:-1', 10) == [1, 2, 3, 4, 5, 6, 7, 8]


def test_parse_param_idx_explicit_reverse_step_can_use_range() -> None:
    assert parse_param_idx('7:3:-1', 10) == [7, 6, 5, 4]


def test_parse_param_idx_strips_whitespace() -> None:
    assert parse_param_idx(' 3 , 7 ', 10) == [3, 7]


def test_parse_param_idx_zfill() -> None:
    assert parse_param_idx('2-7#3', 10) == ['002', '003', '004', '005', '006', '007']
    assert parse_param_idx('02-007') == [2, 3, 4, 5, 6, 7]
    assert parse_param_idx('02-007', zfilled=True) == ['002', '003', '004', '005', '006', '007']
    assert parse_param_idx(':05', 10, zfilled=True) == ['00', '01', '02', '03', '04']
    assert parse_param_idx('02,2345', zfilled=True) == ['0002', '2345']


def test_parse_param_idx_sort_and_dedup() -> None:
    result = parse_param_idx('7,3,5,3', 10, sort=True, dedup=True)
    assert result == [3, 5, 7]
    assert set(result) == {3, 5, 7}


def test_parse_param_idx_slice_without_max_len_when_self_contained() -> None:
    # 这些写法不依赖 max_len，不应报错
    assert parse_param_idx(':5', None) == [0, 1, 2, 3, 4]
    assert parse_param_idx('3::-1', None) == [3, 2, 1, 0]
    assert parse_param_idx('-1:5', None) == [0, 1, 2, 3, 4]


def test_parse_param_idx_open_ended_slice_requires_max_len() -> None:
    with pytest.raises(ValueError, match='max_len'):
        parse_param_idx('3: ', None)


def test_parse_param_idx_reverse_slice_requires_max_len() -> None:
    with pytest.raises(ValueError, match='max_len'):
        parse_param_idx('::-1', None)


def test_parse_param_idx_invalid_slice_format_raises() -> None:
    with pytest.raises(ValueError, match='Invalid slice format'):
        parse_param_idx('1:2:3:4', 10)


def test_parse_param_idx_zero_step_raises() -> None:
    with pytest.raises(ValueError, match='step cannot be 0'):
        parse_param_idx('1:5:0', 10)


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
