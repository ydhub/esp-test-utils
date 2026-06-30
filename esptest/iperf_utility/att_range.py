# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0
"""Helpers for parsing iperf RSSI/ATT sweep ranges."""

import logging
from typing import List, Sequence, Union

ExpectedRangeInput = Union[str, Sequence[int], None]


def parse_expected_rssi_range(value: ExpectedRangeInput) -> List[int]:
    """
    Parse expected range configuration into expected RSSI points.

    Supported formats:
      - ``start_rssi,end_rssi,step``: legacy RSSI range, expanded to RSSI points.
      - ``rssi0,rssi1,(start_rssi,end_rssi,step)``: explicit RSSI points
        plus expandable RSSI range segments.
    """
    if value is None:
        value = (-40, -97, 2)
    if isinstance(value, (list, tuple)):
        values = [int(v) for v in value]
    else:
        values = _parse_expected_range_string(str(value))
    if len(values) < 1:
        raise ValueError(f'expected_range needs at least 1 numbers, got: {value!r}')
    if len(values) == 3 and all(v <= 0 for v in values[:2]) and values[2] > 0:
        values = _expand_range_values(*values)
    return _sort_expected_rssi_list(values, value)


def _sort_expected_rssi_list(values: Sequence[int], original_value: ExpectedRangeInput) -> List[int]:
    sorted_values = sorted(values, reverse=True)
    if sorted_values[0] > 0:
        raise ValueError(f'expected_rssi_list first value must be <= 0, got: {original_value!r}')
    return sorted_values


def _expand_range_values(start: int, end: int, step: int) -> List[int]:
    step = abs(step) if start <= end else -abs(step)
    expanded = []
    cur = start
    if step > 0:
        while cur <= end:
            expanded.append(cur)
            cur += step
    else:
        while cur >= end:
            expanded.append(cur)
            cur += step
    return expanded


def _parse_expected_range_string(value: str) -> List[int]:
    values = []
    for token in _split_top_level_commas(value):
        token = token.strip()
        if not token:
            continue
        if token.startswith('(') and token.endswith(')'):
            values.extend(_expand_range_token(token[1:-1], value))
        else:
            values.append(int(token))
    return values


def _split_top_level_commas(value: str) -> List[str]:
    tokens = []
    start = 0
    depth = 0
    for idx, char in enumerate(value):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth < 0:
                raise ValueError(f'unmatched ")" in expected_range: {value!r}')
        elif char == ',' and depth == 0:
            tokens.append(value[start:idx])
            start = idx + 1
    if depth != 0:
        raise ValueError(f'unmatched "(" in expected_range: {value!r}')
    tokens.append(value[start:])
    return tokens


def _expand_range_token(token: str, original_value: str) -> List[int]:
    parts = [int(v.strip()) for v in token.split(',') if v.strip()]
    if len(parts) != 3:
        raise ValueError(f'range segment needs 3 numbers "(start,end,step)", got: {original_value!r}')

    start, end, step = parts
    if step == 0:
        raise ValueError(f'range segment step must not be 0, got: {original_value!r}')

    return _expand_range_values(start, end, step)


def _rssi_points_to_att_list(initial_rssi: int, rssi_values: Sequence[int], max_att: int) -> List[int]:
    atts: List[int] = []
    min_rssi = min(rssi_values)
    if min_rssi > initial_rssi:
        raise ValueError(f'minimum RSSI {min_rssi} is greater than initial RSSI {initial_rssi}')
    expected_max_att = initial_rssi - min_rssi
    if expected_max_att > max_att + 2:
        raise ValueError(f'expected maximum ATT {expected_max_att} is greater than max ATT {max_att}')
    for target_rssi in rssi_values:
        att = initial_rssi - target_rssi
        if att > max_att:
            logging.warning(
                '[Utility] Stop at RSSI target %s; required ATT %s exceeds max %s',
                target_rssi,
                att,
                max_att,
            )
            break
        atts.append(att)
    logging.info('[Utility] Expected RSSI list: %s', list(rssi_values))
    logging.info('[Utility] Converted ATT list: %s', atts)
    return atts


def limit_att_range(initial_rssi: int, max_att: int, expected_rssi_list: List[int]) -> List[int]:
    """
    Convert parsed expected_rssi_list to ATT values capped by max_att.
    """
    return _rssi_points_to_att_list(initial_rssi, expected_rssi_list, max_att)
