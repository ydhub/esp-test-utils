from typing import List

import pytest

from esptest.iperf_utility.att_range import limit_att_range, parse_expected_rssi_range


@pytest.mark.parametrize(
    'config, expected',
    [
        (
            '-40,-97,2',
            [
                -40,
                -42,
                -44,
                -46,
                -48,
                -50,
                -52,
                -54,
                -56,
                -58,
                -60,
                -62,
                -64,
                -66,
                -68,
                -70,
                -72,
                -74,
                -76,
                -78,
                -80,
                -82,
                -84,
                -86,
                -88,
                -90,
                -92,
                -94,
                -96,
            ],
        ),
        ('-60,-40,-50', [-40, -50, -60]),
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
    assert parse_expected_rssi_range(config) == expected


def test_parse_expected_range_rejects_positive_rssi() -> None:
    with pytest.raises(ValueError, match='first value must be <= 0'):
        parse_expected_rssi_range('1,-40,-50')


@pytest.mark.parametrize(
    'initial_rssi, config, expected_att',
    [
        (-35, '-40,-97,2', list(range(5, 62, 2))),
        (-35, '-60,-40,-50', [5, 15, 25]),
        (
            0,
            '0,-10,-20,(-30,-97,3)',
            [0, 10, 20, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57, 60, 63, 66, 69, 72, 75, 78, 81, 84, 87, 90, 93, 96],
        ),
    ],
)
def test_limit_att_range_dry_run_configs(initial_rssi: int, config: str, expected_att: List[int]) -> None:
    expected_list = parse_expected_rssi_range(config)
    assert limit_att_range(initial_rssi, 200, expected_list) == expected_att


@pytest.mark.parametrize(
    'initial_rssi, config',
    [
        (0, '0,-97,3'),
        (0, '0,-10,-20,(-30,-97,3)'),
    ],
)
def test_limit_att_range_rejects_att_over_max(initial_rssi: int, config: str) -> None:
    expected_list = parse_expected_rssi_range(config)
    with pytest.raises(ValueError, match='expected maximum ATT 96 is greater than max ATT 90'):
        limit_att_range(initial_rssi, 90, expected_list)
