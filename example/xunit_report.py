import logging
from pathlib import Path

from esptest.testcase.result import (
    ResultDetail,
    TestCaseResult,
    TestCaseStatus,
    TestSuiteResult,
    TestSuitesResult,
)
from esptest.testcase.xunit import (
    XunitLogger,
    generate_xunit_xml,
    parse_xunit_xml,
    save_xunit_xml,
)


def xunit_logger_example(output_dir: str) -> Path:
    """Record test cases incrementally with ``XunitLogger``.

    ``XunitLogger`` flushes an xUnit XML report to disk after each case (and
    periodically while a case streams output), so a partial report survives even
    if the runner crashes mid-test.
    """
    logger = XunitLogger(output_dir, suite_name='wifi-suite')
    logger.set_config({'package': 'esp-test-utils', 'file': 'test_wifi.py'})

    # A passing case: stream some serial output, then close it as PASSED.
    logger.begin_case('test_connect', classname='wifi.station')
    logger.add_sys_out('connecting to AP ...')
    logger.add_sys_out('got ip 192.168.1.23')
    logger.end_case()

    # A failing case: end_case(result=False) marks it FAILED with a message.
    logger.begin_case('test_disconnect', classname='wifi.station')
    logger.add_sys_err('serial closed unexpectedly')
    logger.end_case(result=False, message='disconnect timeout', failure_type='timeout')

    # A skipped case.
    logger.begin_case('test_wpa3', classname='wifi.station')
    logger.add_skipped('target does not support WPA3')
    logger.end_case()

    # A performance case: attach a ``ResultDetail`` object to the running case via
    # ``add_result_detail`` with a relative file name (relative to the report dir),
    # then persist it to JSON at that path so the raw numbers are embedded in the
    # report. ``add_result_detail`` stores the relative path on the detail and in
    # ``result_detail_files`` for us.
    logger.begin_case('test_tcp_tx_throughput', classname='iperf.tcp')
    logger.add_sys_out('running iperf tcp tx for 60s ...')
    assert logger.running_case is not None
    detail_rel_path = 'result_details/test_tcp_tx_throughput.json'
    detail = logger.running_case.add_result_detail(
        ResultDetail(
            type='throughput',
            context='iperf tcp tx',
            params={'proto': 'tcp', 'direction': 'tx', 'target': 'esp32'},
            result={'throughput_mbps': 94.2, 'unit': 'Mbits/sec'},
            brief_message='tcp tx 94.2 Mbits/sec',
        ),
        file_name=detail_rel_path,
    )
    detail.save_json(Path(output_dir) / detail_rel_path)
    logger.end_case()

    report_path = logger.flush(force=True)
    logging.critical(f'xUnit report written to: {report_path}')
    return report_path


def build_report_from_dataclasses(output_dir: str) -> Path:
    """Build a report from result dataclasses and serialize it in one shot.

    Use this when the full set of results is already known (e.g. converting
    another framework's results into xUnit XML).
    """
    tcp_tx = TestCaseResult(
        name='test_tcp_tx',
        classname='iperf.tcp',
        duration=60.0,
        stdout='throughput 94.2 Mbits/sec',
        properties={'arch': 'amd64'},
    )
    # Attach a performance result and persist it next to the report. The relative
    # path is recorded on the case so ``parse_xunit_xml`` can auto-load it later.
    tcp_tx_detail_rel = 'result_details/test_tcp_tx.json'
    tcp_tx.add_result_detail(
        ResultDetail(
            type='throughput',
            context='iperf tcp tx',
            result={'throughput': 94.2, 'unit': 'Mbits/sec'},
        ),
        file_name=tcp_tx_detail_rel,
    ).save_json(Path(output_dir) / tcp_tx_detail_rel)

    suites = TestSuitesResult(
        name='esp-test-utils',
        test_suites=[
            TestSuiteResult(
                name='iperf',
                test_cases=[
                    tcp_tx,
                    TestCaseResult(
                        name='test_tcp_rx',
                        classname='iperf.tcp',
                        status=TestCaseStatus.FAILED,
                        message='throughput too low',
                        failure_type='performance',
                    ),
                ],
            )
        ],
    )

    xml_text = generate_xunit_xml(suites)
    logging.critical(f'Generated xUnit XML:\n{xml_text}')

    report_path = save_xunit_xml(suites, Path(output_dir) / 'iperf_result.xml')
    logging.critical(f'Saved report to: {report_path}')
    return report_path


def parse_report_example(report_path: Path) -> None:
    """Read an existing xUnit XML report back into result dataclasses."""
    suites = parse_xunit_xml(report_path)
    logging.critical(f'total tests={suites.tests}, failures={suites.failures}, errors={suites.errors}')
    for suite in suites.test_suites:
        for case in suite.test_cases:
            logging.critical(f'  [{case.status}] {suite.name}::{case.name}')
            # Only show the fields that are actually populated for this case.
            if case.duration is not None:
                logging.critical(f'      duration: {case.duration}s')
            if case.message:
                fail_type = f' ({case.failure_type})' if case.failure_type else ''
                logging.critical(f'      message{fail_type}: {case.message}')
            if case.properties:
                logging.critical(f'      properties: {case.properties}')
            # result_details are auto-loaded from the referenced json files on parse,
            # so we can print the parsed content directly instead of just file paths.
            for detail in case.result_details:
                logging.critical(f'      result_detail ({detail.file}):')
                for line in detail.to_text().splitlines():
                    logging.critical(f'        {line}')
            if case.stdout:
                logging.critical(f'      stdout: {case.stdout}')
            if case.stderr:
                logging.critical(f'      stderr: {case.stderr}')


def main() -> None:
    logging.basicConfig(level=logging.CRITICAL)

    xunit_root_dir = './xunit_report'
    Path(xunit_root_dir).mkdir(parents=True, exist_ok=True)

    logger_report = xunit_logger_example(xunit_root_dir)
    parse_report_example(logger_report)

    dataclass_report = build_report_from_dataclasses(xunit_root_dir)
    parse_report_example(dataclass_report)


if __name__ == '__main__':
    main()
