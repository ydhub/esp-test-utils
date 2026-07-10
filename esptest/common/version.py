import re
from typing import List, Optional, Tuple, Union

from packaging.version import Version

VersionLike = Union[str, Version]
VersionRange = Tuple[Version, Optional[Version], bool, bool]


class VersionLimit:
    """
    Represent a set of supported versions as one or more ranges.

    Supported string formats:

    - ``v1.0`` means ``v1.0`` to unlimited.
    - Patch or multi-part versions are supported, for example ``v1.0.1`` and ``v1.0.0-v2.0.3``.
    - ``v1.0-v2.0`` means the closed range ``[v1.0, v2.0]``.
    - ``[v1.0-v2.0)``, ``(v1.0-v2.0]``, and ``(v1.0-v2.0)`` express open/closed boundaries;
      for example, ``(v3.0-v4.0]`` excludes ``v3.0`` and ``v3.0.0``, but includes ``v3.0.1``.
    - ``(v1.0-)`` means versions greater than ``v1.0`` to unlimited.
    - Use ``;`` to combine multiple ranges, for example ``v1.0-v2.0; v4.0``.

    ``&`` returns the intersection, ``|`` returns the union, and ``remove()`` subtracts ranges.
    """

    VERSION_LIMIT_PATTERN = re.compile(
        r'^\s*(?P<left>[\[\(])?\s*'
        r'(?P<min_version>v?\d+(?:\.\d+)*)'
        r'(?:\s*-\s*(?P<max_version>v?\d+(?:\.\d+)*)?)?'
        r'\s*(?P<right>[\]\)])?\s*$'
    )
    EMPTY_VERSION_LIMIT_STR = '<empty>'

    def __init__(self, version_limit: str = '') -> None:
        self._match_all = not bool(version_limit)
        self._ranges = []  # type: List[VersionRange]
        if version_limit:
            if version_limit.strip() == self.EMPTY_VERSION_LIMIT_STR:
                self._match_all = False
            else:
                self._ranges = self._parse_version_limit(version_limit)

    @classmethod
    def _from_ranges(cls, ranges: List[VersionRange]) -> 'VersionLimit':
        limit = cls()
        limit._match_all = False
        limit._ranges = ranges
        return limit

    @classmethod
    def _to_version_limit(cls, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        return other if isinstance(other, VersionLimit) else cls(other)

    @classmethod
    def _parse_version_limit(cls, version_limit: str) -> List[VersionRange]:
        ranges = []  # type: List[VersionRange]
        for item in version_limit.split(';'):
            match = cls.VERSION_LIMIT_PATTERN.match(item)
            if not match:
                raise ValueError(f'Invalid version limit: {version_limit}')

            left_boundary = match.group('left')
            right_boundary = match.group('right')
            if bool(left_boundary) != bool(right_boundary):
                raise ValueError(f'Invalid version limit range: {item.strip()}')

            min_version = cls._parse_version(match.group('min_version'))
            max_version = cls._parse_version(match.group('max_version')) if match.group('max_version') else None
            if max_version is not None and max_version < min_version:
                raise ValueError(f'Invalid version limit range: {item.strip()}')

            min_inclusive = left_boundary != '('
            max_inclusive = right_boundary != ')'
            ranges.append((min_version, max_version, min_inclusive, max_inclusive))
        return cls._normalize_ranges(ranges)

    @staticmethod
    def _parse_version(version: Optional[VersionLike]) -> Optional[Version]:
        if version is None:
            return None
        if isinstance(version, Version):
            return version
        return Version(version[1:] if version.startswith('v') else version)

    def __and__(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        other_limit = self._to_version_limit(other)
        if self._match_all:
            return other_limit
        if other_limit._match_all:
            return self

        ranges = []
        for self_range in self._ranges:
            for other_range in other_limit._ranges:
                intersection = self._intersect_range(self_range, other_range)
                if intersection is not None:
                    ranges.append(intersection)

        return self._from_ranges(ranges)

    def __rand__(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        return self & other

    def __or__(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        other_limit = self._to_version_limit(other)
        if self._match_all or other_limit._match_all:
            return self.__class__()

        return self._from_ranges(self._normalize_ranges(self._ranges + other_limit._ranges))

    def __ror__(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        return self | other

    def add(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        return self | other

    def __add__(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        return self.add(other)

    def __radd__(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        return self.add(other)

    def __sub__(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        return self.remove(other)

    def __rsub__(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        return self._to_version_limit(other).remove(self)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VersionLimit):
            return False
        return self._match_all == other._match_all and self._ranges == other._ranges

    def __hash__(self) -> int:
        return hash((self._match_all, tuple(self._ranges)))

    def is_any(self) -> bool:
        return self._match_all

    def is_empty(self) -> bool:
        return not self._match_all and not self._ranges

    @classmethod
    def _normalize_ranges(cls, ranges: List[VersionRange]) -> List[VersionRange]:
        if not ranges:
            return []

        normalized_ranges = []  # type: List[VersionRange]
        for version_range in sorted(ranges, key=lambda item: item[0]):
            if not normalized_ranges:
                normalized_ranges.append(version_range)
                continue

            last_range = normalized_ranges[-1]
            if cls._can_merge_ranges(last_range, version_range):
                normalized_ranges[-1] = cls._merge_ranges(last_range, version_range)
            else:
                normalized_ranges.append(version_range)

        return normalized_ranges

    @staticmethod
    def _can_merge_ranges(left: VersionRange, right: VersionRange) -> bool:
        left_max = left[1]
        if left_max is None:
            return True
        if right[0] < left_max:
            return True
        return right[0] == left_max and (left[3] or right[2])

    @classmethod
    def _merge_ranges(cls, left: VersionRange, right: VersionRange) -> VersionRange:
        max_version, max_inclusive = cls._max_upper_bound(left[1], left[3], right[1], right[3])
        return left[0], max_version, left[2], max_inclusive

    @classmethod
    def _intersect_range(cls, left: VersionRange, right: VersionRange) -> Optional[VersionRange]:
        min_version, min_inclusive = cls._max_lower_bound(left[0], left[2], right[0], right[2])
        max_version, max_inclusive = cls._min_upper_bound(left[1], left[3], right[1], right[3])
        if cls._is_valid_range(min_version, max_version, min_inclusive, max_inclusive):
            return min_version, max_version, min_inclusive, max_inclusive
        return None

    @staticmethod
    def _max_lower_bound(
        left: Version, left_inclusive: bool, right: Version, right_inclusive: bool
    ) -> Tuple[Version, bool]:
        if left > right:
            return left, left_inclusive
        if right > left:
            return right, right_inclusive
        return left, left_inclusive and right_inclusive

    @staticmethod
    def _min_upper_bound(
        left: Optional[Version], left_inclusive: bool, right: Optional[Version], right_inclusive: bool
    ) -> Tuple[Optional[Version], bool]:
        if left is None:
            return right, right_inclusive
        if right is None:
            return left, left_inclusive
        if left < right:
            return left, left_inclusive
        if right < left:
            return right, right_inclusive
        return left, left_inclusive and right_inclusive

    @staticmethod
    def _max_upper_bound(
        left: Optional[Version], left_inclusive: bool, right: Optional[Version], right_inclusive: bool
    ) -> Tuple[Optional[Version], bool]:
        if left is None or right is None:
            return None, True
        if left > right:
            return left, left_inclusive
        if right > left:
            return right, right_inclusive
        return left, left_inclusive or right_inclusive

    @staticmethod
    def _is_valid_range(
        min_version: Version, max_version: Optional[Version], min_inclusive: bool, max_inclusive: bool
    ) -> bool:
        if max_version is None:
            return True
        if min_version < max_version:
            return True
        return min_version == max_version and min_inclusive and max_inclusive

    def remove(self, other: Union[str, 'VersionLimit']) -> 'VersionLimit':
        other_limit = self._to_version_limit(other)
        if self._match_all:
            return self
        if other_limit._match_all:  # pylint: disable=protected-access
            return self._from_ranges([])

        ranges = self._ranges
        for other_range in other_limit._ranges:  # pylint: disable=protected-access
            next_ranges = []
            for version_range in ranges:
                next_ranges.extend(self._remove_range(version_range, other_range))
            ranges = next_ranges

        return self._from_ranges(ranges)

    @classmethod
    def _remove_range(cls, version_range: VersionRange, remove_range: VersionRange) -> List[VersionRange]:
        intersection = cls._intersect_range(version_range, remove_range)
        if intersection is None:
            return [version_range]

        min_version, max_version, min_inclusive, max_inclusive = version_range
        remove_min, remove_max = remove_range[0], remove_range[1]
        ranges = []

        left_range = (min_version, remove_min, min_inclusive, not remove_range[2])
        if cls._is_valid_range(*left_range):
            ranges.append(left_range)

        if remove_max is not None:
            right_range = (remove_max, max_version, not remove_range[3], max_inclusive)
            if cls._is_valid_range(*right_range):
                ranges.append(right_range)

        return ranges

    def contains(self, version: VersionLike) -> bool:
        if self._match_all:
            return True

        version_obj = self._parse_version(version)
        for min_version, max_version, min_inclusive, max_inclusive in self._ranges:
            lower_match = version_obj > min_version or (min_inclusive and version_obj == min_version)
            upper_match = (
                max_version is None or version_obj < max_version or (max_inclusive and version_obj == max_version)
            )
            if lower_match and upper_match:
                return True
        return False

    def __contains__(self, version: VersionLike) -> bool:
        return self.contains(version)

    def __str__(self) -> str:
        if self._match_all:
            return ''
        if not self._ranges:
            return self.EMPTY_VERSION_LIMIT_STR

        version_ranges = []
        for version_range in self._ranges:
            version_ranges.append(self._format_range(version_range))
        return ';'.join(version_ranges)

    @staticmethod
    def _format_range(version_range: VersionRange) -> str:
        min_version, max_version, min_inclusive, max_inclusive = version_range
        if max_version is None:
            if min_inclusive:
                return f'v{min_version}'
            return f'(v{min_version}-)'

        if min_inclusive and max_inclusive:
            return f'v{min_version}-v{max_version}'

        left_boundary = '[' if min_inclusive else '('
        right_boundary = ']' if max_inclusive else ')'
        return f'{left_boundary}v{min_version}-v{max_version}{right_boundary}'
