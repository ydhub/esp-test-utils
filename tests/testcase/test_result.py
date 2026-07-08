import json
from pathlib import Path

from esptest.testcase.result import (
    ResultDetail,
    TestCaseResult,
    TestCaseStatus,
    TestSuiteResult,
    TestSuitesResult,
)


def test_result_detail_to_dict_contains_structured_content() -> None:
    detail = ResultDetail(
        type='performance',
        context='iperf tcp tx result',
        params={'target': 'esp32', 'att': 30},
        result={'throughput': 100.5, 'unit': 'Mbps'},
        brief_message='throughput is stable',
        started_at='2026-07-07T10:00:00Z',
        finished_at='2026-07-07T10:01:00Z',
    )

    assert detail.to_dict() == {
        'type': 'performance',
        'context': 'iperf tcp tx result',
        'params': {'target': 'esp32', 'att': 30},
        'result': {'throughput': 100.5, 'unit': 'Mbps'},
        'brief_message': 'throughput is stable',
        'started_at': '2026-07-07T10:00:00Z',
        'finished_at': '2026-07-07T10:01:00Z',
    }


def test_result_detail_save_and_load_json(tmp_path: Path) -> None:
    path = tmp_path / 'details' / 'iperf.json'
    detail = ResultDetail(
        type='performance',
        context='iperf result',
        params={'target': 'esp32'},
        result={'value': 100.5},
        brief_message='ok',
    )

    saved_path = detail.save_json(path)
    loaded = ResultDetail.load_json(saved_path)

    assert saved_path == path
    assert json.loads(path.read_text(encoding='utf-8')) == detail.to_dict()
    assert loaded == detail


def test_result_detail_save_text_and_markdown(tmp_path: Path) -> None:
    detail = ResultDetail(
        type='analysis',
        context='wifi is stable',
        params={'target': 'esp32'},
        result={'success_rate': 0.99},
        brief_message='no packet loss',
    )

    text_path = detail.save_text(tmp_path / 'detail.txt')
    markdown_path = detail.save_markdown(tmp_path / 'detail.md')

    text = text_path.read_text(encoding='utf-8')
    markdown = markdown_path.read_text(encoding='utf-8')
    assert 'Type: analysis' in text
    assert 'Context: wifi is stable' in text
    assert 'Brief Message: no packet loss' in text
    assert '# analysis' in markdown
    assert '## Params' in markdown
    assert '"success_rate": 0.99' in markdown


def test_test_case_result_uses_result_detail_files() -> None:
    case = TestCaseResult(
        name='test_tcp_tx',
        result_detail_files=[
            'result_details/test_tcp_tx.json',
            'result_details/test_tcp_tx.md',
        ],
    )

    assert case.result_detail_files == [
        'result_details/test_tcp_tx.json',
        'result_details/test_tcp_tx.md',
    ]


def test_test_suites_result_aggregates_nested_case_counts() -> None:
    suites = TestSuitesResult(
        name='all-tests',
        test_suites=[
            TestSuiteResult(
                name='wifi',
                test_cases=[
                    TestCaseResult(name='test_connect', classname='wifi.station', duration=1.2),
                    TestCaseResult(name='test_disconnect', status=TestCaseStatus.FAILED, message='disconnect failed'),
                ],
            ),
            TestSuiteResult(
                name='mesh',
                test_cases=[
                    TestCaseResult(name='test_join', status=TestCaseStatus.ERROR, duration=0.3),
                    TestCaseResult(name='test_skip', status=TestCaseStatus.SKIPPED),
                ],
            ),
        ],
    )

    assert suites.tests == 4
    assert suites.failures == 1
    assert suites.errors == 1
    assert suites.skipped == 1
    assert suites.time == 1.5
