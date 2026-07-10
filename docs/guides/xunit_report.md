# xUnit reporting

The `esptest.testcase` package produces JUnit/xUnit-style XML reports that CI
systems (GitLab, Jenkins, ...) understand. There are two ways to build a
report:

1. **`XunitLogger`** — record cases incrementally while a test run executes.
2. **Result dataclasses** — build the full result tree and serialize it in one
   shot (handy for converting another framework's results).

## Recording incrementally with `XunitLogger`

`XunitLogger` flushes the XML to disk after each case (and periodically while a
case streams output), so a partial report survives even if the runner crashes
mid-test.

```python
from esptest.testcase.xunit import XunitLogger

logger = XunitLogger('./xunit_report', suite_name='wifi-suite')
logger.set_config({'package': 'esp-test-utils', 'file': 'test_wifi.py'})

# passing case
logger.begin_case('test_connect', classname='wifi.station')
logger.add_sys_out('connecting to AP ...')
logger.end_case()

# failing case
logger.begin_case('test_disconnect', classname='wifi.station')
logger.add_sys_err('serial closed unexpectedly')
logger.end_case(result=False, message='disconnect timeout', failure_type='timeout')

# skipped case
logger.begin_case('test_wpa3', classname='wifi.station')
logger.add_skipped('target does not support WPA3')
logger.end_case()

report_path = logger.flush(force=True)
```

`end_case(result=False, ...)` marks the running case FAILED; `add_skipped`
marks it SKIPPED.

## Attaching performance details

A case can carry structured performance data via `ResultDetail`. Persist it to
JSON next to the report using a path relative to the report directory; the
relative path is recorded on the case so it is auto-loaded when the report is
parsed back.

```python
from pathlib import Path

from esptest.testcase.result import ResultDetail

logger.begin_case('test_tcp_tx_throughput', classname='iperf.tcp')
detail_rel = 'result_details/test_tcp_tx_throughput.json'
detail = logger.running_case.add_result_detail(
    ResultDetail(
        type='throughput',
        context='iperf tcp tx',
        params={'proto': 'tcp', 'direction': 'tx'},
        result={'throughput_mbps': 94.2, 'unit': 'Mbits/sec'},
        brief_message='tcp tx 94.2 Mbits/sec',
    ),
    file_name=detail_rel,
)
detail.save_json(Path('./xunit_report') / detail_rel)
logger.end_case()
```

## Building from dataclasses

When the full set of results is already known, assemble the tree and serialize
it directly:

```python
from esptest.testcase.result import (
    TestCaseResult,
    TestCaseStatus,
    TestSuiteResult,
    TestSuitesResult,
)
from esptest.testcase.xunit import generate_xunit_xml, save_xunit_xml

suites = TestSuitesResult(
    name='esp-test-utils',
    test_suites=[
        TestSuiteResult(
            name='iperf',
            test_cases=[
                TestCaseResult(name='test_tcp_tx', classname='iperf.tcp', duration=60.0),
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

xml_text = generate_xunit_xml(suites)          # XML as a string
save_xunit_xml(suites, './xunit_report/iperf_result.xml')  # write to disk
```

## Parsing an existing report

`parse_xunit_xml` reads an XML report back into the result dataclasses,
auto-loading any referenced `ResultDetail` JSON files:

```python
from esptest.testcase.xunit import parse_xunit_xml

suites = parse_xunit_xml('./xunit_report/iperf_result.xml')
print(f'tests={suites.tests}, failures={suites.failures}, errors={suites.errors}')
for suite in suites.test_suites:
    for case in suite.test_cases:
        print(f'[{case.status}] {suite.name}::{case.name}')
```

See `example/xunit_report.py` in the repository for a complete, runnable
walk-through.
