from unittest import mock

import pytest

from esptest.common.parser import expand_to_list, parse_param_idx


def test_expand_env_vars_expands_braced_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    from esptest.common import expand_env_vars

    monkeypatch.setenv('ESPTEST_BIN_DIR', '/tmp/bin')

    assert expand_env_vars('${ESPTEST_BIN_DIR}/app.bin') == '/tmp/bin/app.bin'


def test_expand_env_vars_uses_given_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from esptest.common import expand_env_vars

    monkeypatch.setenv('ESPTEST_BIN_DIR', '/tmp/bin')

    assert (
        expand_env_vars(
            '${ESPTEST_BIN_DIR}/app.bin',
            env={'ESPTEST_BIN_DIR': '/custom/bin'},
        )
        == '/custom/bin/app.bin'
    )


def test_expand_env_vars_logs_same_replacement_once() -> None:
    from esptest.common import expand_env_vars, parser

    parser._log_env_var_replacement_once.cache_clear()  # pylint: disable=protected-access
    with mock.patch.object(parser.logger, 'info') as logger_info:
        assert (
            expand_env_vars(
                '${ESPTEST_BIN_DIR}/${ESPTEST_BIN_DIR}/${ESPTEST_LOG_DIR}/${ESPTEST_LOG_DIR}',
                env={'ESPTEST_BIN_DIR': '/custom/bin', 'ESPTEST_LOG_DIR': '/custom/log'},
            )
            == '/custom/bin//custom/bin//custom/log//custom/log'
        )

        logger_info.assert_any_call('Replace environment variable `ESPTEST_BIN_DIR` -> `/custom/bin`')
        logger_info.assert_any_call('Replace environment variable `ESPTEST_LOG_DIR` -> `/custom/log`')
        assert logger_info.call_count == 2


def test_expand_env_vars_logs_same_replacement_once_across_calls() -> None:
    from esptest.common import expand_env_vars, parser

    parser._log_env_var_replacement_once.cache_clear()  # pylint: disable=protected-access
    with mock.patch.object(parser.logger, 'info') as logger_info:
        assert expand_env_vars('${ESPTEST_CACHE_DIR}', env={'ESPTEST_CACHE_DIR': '/custom/cache'}) == '/custom/cache'
        assert expand_env_vars('${ESPTEST_CACHE_DIR}', env={'ESPTEST_CACHE_DIR': '/custom/cache'}) == '/custom/cache'

        logger_info.assert_called_once_with('Replace environment variable `ESPTEST_CACHE_DIR` -> `/custom/cache`')


def test_expand_env_vars_ignores_unbraced_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    from esptest.common import expand_env_vars

    monkeypatch.setenv('ESPTEST_BIN_DIR', '/tmp/bin')

    assert expand_env_vars('$ESPTEST_BIN_DIR/${ESPTEST_BIN_DIR}') == '$ESPTEST_BIN_DIR//tmp/bin'


def test_expand_env_vars_raises_for_missing_variables() -> None:
    from esptest.common import expand_env_vars

    with pytest.raises(KeyError, match='Environment variable `ESPTEST_MISSING_BIN_DIR` is not defined'):
        expand_env_vars('${ESPTEST_MISSING_BIN_DIR}/app.bin')


def test_expand_env_vars_raises_for_missing_variables_in_given_env() -> None:
    from esptest.common import expand_env_vars

    with pytest.raises(KeyError, match='Environment variable `ESPTEST_MISSING_BIN_DIR` is not defined'):
        expand_env_vars('${ESPTEST_MISSING_BIN_DIR}/app.bin', env={})


def test_parse_param_idx_invalid_input() -> None:
    with pytest.raises(ValueError, match='Invalid input'):
        parse_param_idx('', 10)
    with pytest.raises(ValueError, match='Invalid input'):
        parse_param_idx(None, 10)  # type: ignore
    with pytest.raises(ValueError, match='max_len'):
        parse_param_idx('3: ', None)
    with pytest.raises(ValueError, match='Invalid slice format'):
        parse_param_idx('1:2:3:4', 10)
    with pytest.raises(ValueError, match='max_len'):
        parse_param_idx('3:,11-14', None)


def test_parse_param_idx_single_index() -> None:
    assert parse_param_idx('3', 10) == [3]
    assert parse_param_idx('11') == [11]
    assert parse_param_idx('1,1,3') == [1, 1, 3]


def test_parse_param_idx_range_and_exclusion() -> None:
    assert parse_param_idx('0,2-7,!5', 10) == [0, 2, 3, 4, 6, 7]
    assert parse_param_idx('0-4,!8', 10) == [0, 1, 2, 3, 4]
    assert parse_param_idx('!3,!7', 10) == [0, 1, 2, 4, 5, 6, 8, 9]
    assert parse_param_idx('!3-7', 10) == [0, 1, 2, 8, 9]
    assert parse_param_idx('2-5,!3-4', 10) == [2, 5]


def test_parse_param_idx_with_slice_and_exclusion() -> None:
    assert parse_param_idx('0:,!3,!7', 10) == [0, 1, 2, 4, 5, 6, 8, 9]
    assert parse_param_idx('::-1', 5) == [4, 3, 2, 1, 0]
    # duplicate index
    assert parse_param_idx('3:,5-7', 8) == [3, 4, 5, 6, 7, 5, 6, 7]

    # 与 range(1, -1, 1)（空序列）不同，须为 list 切片语义 all_idx[1:-1]
    assert parse_param_idx('1:-1', 10) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert parse_param_idx('7:3:-1', 10) == [7, 6, 5, 4]
    with pytest.raises(ValueError, match='step cannot be 0'):
        parse_param_idx('1:5:0', 10)
    with pytest.raises(ValueError, match='max_len'):
        parse_param_idx('::-1', None)


def test_parse_param_idx_out_of_range() -> None:
    with pytest.raises(ValueError, match='out of range'):
        parse_param_idx('1', 0)
    with pytest.raises(ValueError, match='max_len'):
        parse_param_idx('::-1', 0)
    # assert parse_param_idx('-1:12', 10) == list(range(10))
    with pytest.raises(ValueError, match='out of range'):
        parse_param_idx('-1:12', 10)


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
    assert parse_param_idx('1', None) == [1]


def test_expand_to_list_string_list() -> None:
    assert expand_to_list('a,b,c') == ['a', 'b', 'c']
    assert expand_to_list('a1,b2,c3') == ['a1', 'b2', 'c3']
    assert expand_to_list('1,1,2,3') == ['1', '1', '2', '3']
    assert expand_to_list('1-3,2') == ['1', '2', '3', '2']
    with pytest.raises(ValueError, match='format error'):
        expand_to_list('abc')
    with pytest.raises(ValueError, match='format error'):
        expand_to_list(':')
    with pytest.raises(ValueError, match='format error'):
        expand_to_list('-1')
    with pytest.raises(ValueError, match='format error'):
        expand_to_list('%')
