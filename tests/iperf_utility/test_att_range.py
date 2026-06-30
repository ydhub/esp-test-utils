from typing import List

import pytest

from esptest.iperf_utility.att_range import limit_att_range, parse_expected_range


@pytest.mark.parametrize(
    'config, expected',
    [
        ('-40,-97,2', [-40, -97, 2]),
        ('0,10,20,30,33,36,39', [0, 10, 20, 30, 33, 36, 39]),
        (
            '0,-10,-20,(-30,-97,3)',
            [
                0,
                -10,
                -20,
                -30,
                -33,
                -36,
                -39,
                -42,
                -45,
                -48,
                -51,
                -54,
                -57,
                -60,
                -63,
                -66,
                -69,
                -72,
                -75,
                -78,
                -81,
                -84,
                -87,
                -90,
                -93,
                -96,
            ],
        ),
    ],
)
def test_parse_expected_range_configs(config: str, expected: List[int]) -> None:
    assert parse_expected_range(config) == expected


@pytest.mark.parametrize(
    'initial_rssi, config, expected_att',
    [
        (-35, '-40,-97,2', list(range(5, 62, 2))),
        (-35, '0,10,20,30,33,36,39', [0, 10, 20, 30, 33, 36, 39]),
        (
            0,
            '0,-10,-20,(-30,-97,3)',
            [0, 10, 20, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84, 87, 90, 93, 96],
        ),
    ],
)
def test_limit_att_range_dry_run_configs(initial_rssi: int, config: str, expected_att: List[int]) -> None:
    expected_list = parse_expected_range(config)
    assert limit_att_range(initial_rssi, 200, expected_list) == expected_att


@pytest.mark.parametrize(
    'initial_rssi, config, expected_att',
    [
        (0, '0,-97,3', list(range(0, 90, 3)) + [90]),
        (
            0,
            '0,-10,-20,(-30,-97,3)',
            [0, 10, 20, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84, 87, 90],
        ),
    ],
)
def test_limit_att_range_caps_at_attenuator_max(initial_rssi: int, config: str, expected_att: List[int]) -> None:
    expected_list = parse_expected_range(config)
    assert limit_att_range(initial_rssi, 90, expected_list) == expected_att
