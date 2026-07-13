import pytest

from esptest.common.version import VersionLimit, version_contains, version_intersect, version_union


def test_version_limit_parses_open_ended_version() -> None:
    limit = VersionLimit('v1.0')

    assert str(limit) == 'v1.0'
    assert limit.contains('v1.0')
    assert limit.contains('v2.0')
    assert not limit.contains('v0.9')


def test_version_limit_parses_closed_range() -> None:
    limit = VersionLimit('v1.0-v2.0')

    assert str(limit) == 'v1.0-v2.0'
    assert limit.contains('v1.0')
    assert limit.contains('v1.5')
    assert limit.contains('v2.0')
    assert not limit.contains('v2.1')


def test_version_limit_parses_multiple_ranges() -> None:
    limit = VersionLimit('v1.0-v2.0; v4.0')

    assert str(limit) == 'v1.0-v2.0;v4.0'
    assert limit.contains('v1.5')
    assert not limit.contains('v3.0')
    assert limit.contains('v4.0')
    assert limit.contains('v5.0')


def test_version_limit_merges_overlapping_ranges_when_parsing() -> None:
    limit = VersionLimit('v3.0-v5.0;v1.0-v3.5;(v5.0-v6.0]')

    assert str(limit) == 'v1.0-v6.0'
    assert limit.contains('v1.0')
    assert limit.contains('v5.0')
    assert limit.contains('v5.0.1')
    assert limit.contains('v6.0')
    assert not limit.contains('v6.1')


@pytest.mark.parametrize(
    'version_limit',
    [
        'v1.0-v0.9',
        '[v1.0-v2.0',
        'v1.0-v2.0]',
        'v1.0;;v2.0',
        'v1.0,v2.0',
        'abc',
    ],
)
def test_version_limit_rejects_invalid_input(version_limit: str) -> None:
    with pytest.raises(ValueError):
        VersionLimit(version_limit)


def test_version_limit_parses_open_and_closed_boundaries() -> None:
    limit = VersionLimit('[v1.0-v2.0); (v3.0-v4.0]')

    assert str(limit) == '[v1.0-v2.0);(v3.0-v4.0]'
    assert limit.contains('v1.0')
    assert limit.contains('v1.99999')
    assert not limit.contains('v2.0')
    assert not limit.contains('v3.0')
    assert not limit.contains('v3.0.0')
    assert limit.contains('v3.0.1')
    assert limit.contains('v4.0')


def test_version_limit_parses_open_ended_exclusive_boundary() -> None:
    limit = VersionLimit('(v1.0-)')

    assert str(limit) == '(v1.0-)'
    assert not limit.contains('v1.0')
    assert limit.contains('v1.1')


def test_version_limit_intersects_multiple_ranges() -> None:
    limit = VersionLimit('v1.0-v3.0; v4.0-v5.0') & VersionLimit('v2.0-v4.5')

    assert str(limit) == 'v2.0-v3.0;v4.0-v4.5'
    assert limit.contains('v2.5')
    assert not limit.contains('v3.5')
    assert limit.contains('v4.5')
    assert not limit.contains('v5.0')


def test_version_limit_and_operator_accepts_string() -> None:
    limit = VersionLimit('v1.0-v3.0') & 'v2.0-v4.0'

    assert str(limit) == 'v2.0-v3.0'
    assert not limit.contains('v1.5')
    assert limit.contains('v2.5')
    assert not limit.contains('v3.5')


def test_version_limit_or_operator_merges_overlapping_ranges() -> None:
    limit = VersionLimit('v1.0-v3.0') | 'v2.0-v4.0'

    assert str(limit) == 'v1.0-v4.0'
    assert limit.contains('v1.0')
    assert limit.contains('v3.5')
    assert not limit.contains('v4.1')


def test_version_limit_or_operator_keeps_disjoint_ranges() -> None:
    limit = VersionLimit('v1.0-v2.0') | VersionLimit('v4.0')

    assert str(limit) == 'v1.0-v2.0;v4.0'
    assert limit.contains('v1.5')
    assert not limit.contains('v3.0')
    assert limit.contains('v5.0')


def test_version_limit_add_merges_ranges() -> None:
    limit = VersionLimit('v1.0-v2.0').add('v2.0-v3.0')

    assert str(limit) == 'v1.0-v3.0'
    assert limit.contains('v2.5')
    assert not limit.contains('v3.1')


def test_version_limit_plus_operator_accepts_string() -> None:
    limit = VersionLimit('v1.0-v2.0') + 'v4.0'

    assert str(limit) == 'v1.0-v2.0;v4.0'
    assert limit.contains('v1.5')
    assert not limit.contains('v3.0')
    assert limit.contains('v5.0')


def test_version_limit_hash_uses_normalized_ranges() -> None:
    left = VersionLimit('v1.0-v2.0; v4.0')
    right = VersionLimit('v1.0-v2.0;v4.0')

    assert str(left) == str(right)
    assert str(left) == 'v1.0-v2.0;v4.0'
    assert left == right
    assert hash(left) == hash(right)
    assert len({left, right}) == 1

    left = VersionLimit('v4.0; [v1.0-v2.0)')
    right = VersionLimit('[v1.0-v2.0);v4.0')

    assert str(left) == str(right)
    assert str(left) == '[v1.0-v2.0);v4.0'
    assert left == right
    assert hash(left) == hash(right)
    assert len({left, right}) == 1


def test_version_limit_minus_operator_removes_range() -> None:
    limit = VersionLimit('v1.0-v5.0') - 'v2.0-v3.0'

    assert str(limit) == '[v1.0-v2.0);(v3.0-v5.0]'
    assert not limit.contains('v2.0')
    assert not limit.contains('v3.0')
    assert limit.contains('v3.5')


def test_reverse_minus_operator_removes_from_string_range() -> None:
    limit = 'v1.0-v5.0' - VersionLimit('v2.0-v3.0')

    assert str(limit) == '[v1.0-v2.0);(v3.0-v5.0]'
    assert limit.contains('v1.5')
    assert not limit.contains('v2.5')


def test_default_version_limit_matches_any_version() -> None:
    limit = VersionLimit()

    assert str(limit) == ''
    assert limit.is_any()
    assert not limit.is_empty()
    assert limit.contains('v0.0')
    assert limit.contains('v99999.0')


def test_version_limit_intersection_without_overlap_is_empty() -> None:
    limit = VersionLimit('v1.0-v2.0') & VersionLimit('v3.0-v4.0')

    assert str(limit) == '<empty>'
    assert not limit.is_any()
    assert limit.is_empty()
    assert not limit.contains('v1.5')
    assert not limit.contains('v3.5')


def test_version_limit_parses_empty_literal() -> None:
    limit = VersionLimit('<empty>')

    assert str(limit) == '<empty>'
    assert not limit.is_any()
    assert limit.is_empty()
    assert not limit.contains('v1.5')
    assert not limit.contains('v3.5')


def test_version_limit_empty_literal_can_be_overridden() -> None:
    class CustomVersionLimit(VersionLimit):
        EMPTY_VERSION_LIMIT_STR = '<none>'

    limit = CustomVersionLimit('<none>')

    assert str(limit) == '<none>'
    assert not limit.is_any()
    assert limit.is_empty()


def test_version_limit_remove_string_range() -> None:
    limit = VersionLimit('v1.0-v5.0').remove('v2.0-v3.0')

    assert str(limit) == '[v1.0-v2.0);(v3.0-v5.0]'
    assert limit.contains('v1.5')
    assert not limit.contains('v2.0')
    assert not limit.contains('v2.5')
    assert not limit.contains('v3.0')
    assert limit.contains('v3.5')


def test_version_limit_remove_version_limit() -> None:
    limit = VersionLimit('v1.0-v3.0; v4.0').remove(VersionLimit('v2.0-v4.5'))

    assert str(limit) == '[v1.0-v2.0);(v4.5-)'
    assert limit.contains('v1.5')
    assert not limit.contains('v2.0')
    assert not limit.contains('v3.0')
    assert not limit.contains('v4.5')
    assert limit.contains('v5.0')


def test_version_limit_remove_all() -> None:
    limit = VersionLimit('v1.0-v2.0').remove('v1.0-v2.0')

    assert str(limit) == '<empty>'
    assert not limit.is_any()
    assert limit.is_empty()
    assert not limit.contains('v1.0')
    assert not limit.contains('v1.5')
    assert not limit.contains('v2.0')


def test_version_contains_in_closed_range() -> None:
    assert version_contains('v1.0-v2.0', 'v1.0')
    assert version_contains('v1.0-v2.0', 'v1.5')
    assert version_contains('v1.0-v2.0', 'v2.0')
    assert not version_contains('v1.0-v2.0', 'v0.9')
    assert not version_contains('v1.0-v2.0', 'v2.1')


def test_version_contains_open_ended_limit() -> None:
    assert version_contains('v1.0', 'v1.0')
    assert version_contains('v1.0', 'v9.0')
    assert not version_contains('v1.0', 'v0.9')


def test_version_contains_half_open_boundary() -> None:
    assert not version_contains('[v1.0-v2.0)', 'v2.0')
    assert version_contains('[v1.0-v2.0)', 'v1.9')
    assert not version_contains('(v1.0-v2.0]', 'v1.0')
    assert version_contains('(v1.0-v2.0]', 'v1.0.1')


def test_version_contains_match_all_and_empty() -> None:
    assert version_contains('', 'v0.0')
    assert version_contains('', 'v999.0')
    assert not version_contains('<empty>', 'v1.0')


def test_version_contains_cache_hits() -> None:
    version_contains.cache_clear()
    try:
        assert version_contains('v1.0-v2.0', 'v1.5')
        assert version_contains.cache_info().hits == 0
        assert version_contains.cache_info().misses == 1

        assert version_contains('v1.0-v2.0', 'v1.5')
        assert version_contains.cache_info().hits == 1
        assert version_contains.cache_info().misses == 1
    finally:
        version_contains.cache_clear()


def test_version_intersect_overlapping_ranges() -> None:
    assert version_intersect('v1.0-v3.0', 'v2.0-v4.0') == 'v2.0-v3.0'


def test_version_intersect_without_overlap_is_empty() -> None:
    assert version_intersect('v1.0-v2.0', 'v3.0-v4.0') == '<empty>'


def test_version_union_merges_overlapping_ranges() -> None:
    assert version_union('v1.0-v3.0', 'v2.0-v4.0') == 'v1.0-v4.0'


def test_version_union_keeps_disjoint_ranges() -> None:
    assert version_union('v1.0-v2.0', 'v4.0') == 'v1.0-v2.0;v4.0'


def test_version_union_merges_adjacent_ranges() -> None:
    assert version_union('v1.0-v2.0', 'v2.0-v3.0') == 'v1.0-v3.0'
