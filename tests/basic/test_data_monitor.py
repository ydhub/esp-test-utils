import re
import threading
import time
from unittest.mock import patch

import esptest.common.data_monitor as data_monitor_module
from esptest.common.data_monitor import DataMonitor, MatchedResult


def test_data_monitor_string_pattern_match_once() -> None:
    monitor = DataMonitor('hello')

    monitor.append_data('uart0', 'abc')
    assert monitor.matched_count == 0
    assert monitor.matched_ports == []
    assert monitor.matched_results == []

    monitor.append_data('uart0', 'hello')
    assert monitor.matched_count == 1
    assert monitor.matched_ports == ['uart0']
    assert monitor.matched_results[0].port_name == 'uart0'
    assert monitor.matched_results[0].match == 'hello'

    # Cache is trimmed after one hit, so appending unrelated data does not
    # re-trigger the same historical match.
    monitor.append_data('uart0', ' world')
    assert monitor.matched_count == 1


def test_data_monitor_regex_pattern_and_callback() -> None:
    callback_calls = []

    def _callback(matched_result: MatchedResult) -> None:
        assert isinstance(matched_result.match, re.Match)
        callback_calls.append(
            (matched_result.key, matched_result.port_name, matched_result.match.group(0), matched_result.timestamp)
        )

    monitor = DataMonitor(re.compile(r'ID:\d+'), callback=_callback)
    monitor.append_data('uart1', 'boot ID:42 ok', timestamp=123.456)

    assert monitor.matched_count == 1
    assert monitor.matched_ports == ['uart1']
    assert monitor.matched_results[0].port_name == 'uart1'
    first_match = monitor.matched_results[0].match
    assert isinstance(first_match, re.Match)
    assert first_match.group(0) == 'ID:42'
    assert monitor.matched_results[0].timestamp == 123.456
    assert callback_calls == [('ID:\\d+', 'uart1', 'ID:42', 123.456)]


def test_data_monitor_regex_matches_all_in_single_append() -> None:
    monitor = DataMonitor(re.compile(r'ID:\d+'))
    monitor.append_data('uart0', 'boot ID:1 mid ID:2 end')

    assert monitor.matched_count == 2
    assert monitor.matched_ports == ['uart0', 'uart0']
    matches = []
    for result in monitor.matched_results:
        assert isinstance(result.match, re.Match)
        matches.append(result.match.group(0))
    assert matches == ['ID:1', 'ID:2']


def test_data_monitor_port_name_filter() -> None:
    monitor = DataMonitor('READY', port_names=['uart2'])

    monitor.append_data('uart0', 'READY')
    assert monitor.matched_count == 0
    assert monitor.matched_ports == []

    monitor.append_data('uart2', 'READY')
    assert monitor.matched_count == 1
    assert monitor.matched_ports == ['uart2']


def test_data_monitor_no_duplicate_hit_without_new_pattern() -> None:
    monitor = DataMonitor('OK')

    monitor.append_data('uart0', 'OK')
    assert monitor.matched_count == 1

    # Appending empty string should not produce a duplicate hit.
    monitor.append_data('uart0', '')
    assert monitor.matched_count == 1


def test_data_monitor_multiple_threads() -> None:
    monitor = DataMonitor(re.compile(r'OK\d+'))

    def _thread_1() -> None:
        monitor.append_data('uart1', 'OK1')

    def _thread_2() -> None:
        monitor.append_data('uart2', 'OK2')

    thread_1 = threading.Thread(target=_thread_1)
    thread_2 = threading.Thread(target=_thread_2)
    thread_1.start()
    thread_2.start()
    thread_1.join()
    thread_2.join()

    assert monitor.matched_count == 2
    assert set(monitor.matched_ports) == {'uart1', 'uart2'}
    for result in monitor.matched_results:
        if result.port_name == 'uart1':
            assert isinstance(result.match, re.Match)
            assert result.match.group(0) == 'OK1'
        elif result.port_name == 'uart2':
            assert isinstance(result.match, re.Match)
            assert result.match.group(0) == 'OK2'
        else:
            assert False


def test_data_monitor_multiple_threads_high_volume() -> None:
    monitor = DataMonitor('OK')
    hit_per_thread = 2000

    def _worker(port_name: str) -> None:
        for _ in range(hit_per_thread):
            monitor.append_data(port_name, 'OK')

    thread_1 = threading.Thread(target=_worker, args=('uart1',))
    thread_2 = threading.Thread(target=_worker, args=('uart2',))
    thread_1.start()
    thread_2.start()
    thread_1.join()
    thread_2.join()

    assert monitor.matched_count == hit_per_thread * 2
    assert len(monitor.matched_results) == hit_per_thread * 2


def test_data_monitor_zero_length_regex_no_hang() -> None:
    monitor = DataMonitor(re.compile(r'.*'))
    monitor.append_data('uart0', 'abc')
    monitor.append_data('uart0', 'def')

    assert monitor.matched_count > 0
    assert monitor.matched_count <= 6  # match len should always > 0 to avoid hang


def test_data_monitor_data_cache_init_thread_safe_for_same_port() -> None:
    monitor = DataMonitor('OK')
    worker_count = 20
    creation_count = 0
    creation_lock = threading.Lock()

    class _SlowDataCache:  # pylint: disable=too-few-public-methods
        def __init__(self) -> None:
            nonlocal creation_count
            time.sleep(0.002)
            self.lock = threading.RLock()
            self.data = ''
            with creation_lock:
                creation_count += 1

    barrier = threading.Barrier(worker_count)

    def _worker() -> None:
        barrier.wait()
        monitor.append_data('uart_same', 'OK')

    with patch.object(data_monitor_module, '_DataCache', _SlowDataCache):
        threads = [threading.Thread(target=_worker) for _ in range(worker_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert creation_count == 1
    assert monitor.matched_count == worker_count
