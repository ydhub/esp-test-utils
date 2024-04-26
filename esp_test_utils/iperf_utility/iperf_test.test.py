import unittest
from unittest.mock import MagicMock

from esp_test_utils.iperf_utility.iperf_test import IperfTestBaseUtility


class TestIperfTestBaseUtility(unittest.TestCase):
    def setUp(self) -> None:
        self.dut_mock = MagicMock()
        self.iperf_test = IperfTestBaseUtility(self.dut_mock)

    def test_run_one_case_raises_not_implemented_error(self) -> None:
        iperf_utility = IperfTestBaseUtility(self.dut_mock)
        with self.assertRaises(NotImplementedError):
            iperf_utility.run_one_case('tcp_tx')


if __name__ == '__main__':
    unittest.main()
