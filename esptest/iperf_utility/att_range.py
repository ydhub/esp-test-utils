# SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
# SPDX-License-Identifier: Apache-2.0
"""Helpers for parsing iperf RSSI/ATT sweep ranges."""

import logging
from typing import List, Sequence, Union

ExpectedRangeInput = Union[str, Sequence[int], None]


def parse_expected_range(value: ExpectedRangeInput) -> List[int]:
    """
    Parse expected range configuration.

    Supported formats:
      - ``start_rssi,end_rssi,step``: legacy RSSI range, converted to ATT.
      - ``att0,att1,att2,...``: explicit ATT list for non-uniform steps.
      - ``rssi0,rssi1,(start_rssi,end_rssi,step)``: explicit RSSI points
        plus expandable RSSI range segments.
    """
    if value is None:
        value = '-40,-97,2'
    if isinstance(value, (list, tuple)):
        values = [int(v) for v in value]
    else:
        values = _parse_expected_range_string(str(value))
    if len(values) < 3:
        raise ValueError(f'expected_range needs at least 3 numbers, got: {value!r}')
    return values


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

    step = abs(step) if start <= end else -abs(step)
    values = []
    cur = start
    if step > 0:
        while cur <= end:
            values.append(cur)
            cur += step
    else:
        while cur >= end:
            values.append(cur)
            cur += step
    return values


def _limit_explicit_att_list(att_values: Sequence[int], max_att: int) -> List[int]:
    limited = []
    for att in att_values:
        if att < 0:
            logging.warning('[Utility] Ignore negative ATT value: %s', att)
            continue
        if att > max_att:
            logging.warning('[Utility] Ignore ATT value over max %s: %s', max_att, att)
            continue
        limited.append(att)
    logging.info('[Utility] Explicit ATT list: %s', limited)
    return limited


def _rssi_points_to_att_list(initial_rssi: int, rssi_values: Sequence[int], max_att: int) -> List[int]:
    atts: List[int] = []
    for target_rssi in rssi_values:
        att = max(0, initial_rssi - target_rssi)
        if att > max_att:
            logging.warning(
                '[Utility] Cap RSSI target %s; required ATT %s exceeds max %s',
                target_rssi,
                att,
                max_att,
            )
            if not atts or atts[-1] != max_att:
                atts.append(max_att)
            break
        atts.append(att)
    logging.info('[Utility] Explicit RSSI list: %s', list(rssi_values))
    logging.info('[Utility] Converted ATT list: %s', atts)
    return atts


def limit_att_range(initial_rssi: int, max_att: int, expected_list: List[int]) -> List[int]:
    """
    Convert parsed expected_list to ATT values capped by max_att.

    Three values keep the original RSSI range behavior. More than three values
    are treated as an explicit ATT list, e.g. ``0,10,20,30,33,36,39``.
    """
    if len(expected_list) != 3 and all(v <= 0 for v in expected_list):
        return _rssi_points_to_att_list(initial_rssi, expected_list, max_att)
    if len(expected_list) != 3:
        return _limit_explicit_att_list(expected_list, max_att)

    start_expected_rssi, end_expected_rssi, step = expected_list
    if step <= 0:
        raise ValueError(f'expected_range step must be positive, got: {step}')

    start_rssi = min(start_expected_rssi, initial_rssi)
    if initial_rssi < start_expected_rssi:
        start_att = 0
        att_range = initial_rssi - end_expected_rssi
    else:
        start_att = initial_rssi - start_expected_rssi
        att_range = start_expected_rssi - end_expected_rssi

    if start_att > max_att:
        logging.warning('[Utility] Cap start ATT %s; exceeds attenuator max %s', start_att, max_att)
        start_att = max_att

    requested_end_att = start_att + att_range
    end_att = min(requested_end_att, max_att)
    logging.info('[Utility] Expected RSSI Range: %s, %s', start_rssi, start_rssi - end_att + start_att)
    logging.info('[Utility] ATT Range: %s-%s, step: %s', start_att, end_att, step)
    atts = list(range(start_att, end_att, step))
    if requested_end_att > max_att and (not atts or atts[-1] != max_att):
        atts.append(max_att)
    return atts
