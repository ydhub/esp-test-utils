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
logger.set_case_properties({'target': 'esp32', 'config': 'release'})
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

`set_case_properties()` merges values into the currently running case; a later
value overwrites an existing key. Calling it without a running case raises
`RuntimeError`. It does not flush immediately—the properties are written by a
later periodic or explicit flush, or when `end_case()` finishes the case.

`end_case(result=False, ...)` marks the running case FAILED; `add_skipped`
marks it SKIPPED.

## Suite config and process-wide defaults

`set_config()` updates the current suite. Known keys are `suite_name`,
`package`, `file`, and `hostname`. Any other key is stored as a suite
property (emitted on the `<testsuite>` / properties section of the report):

```python
logger.set_config({
    'package': 'esp-test-utils',
    'file': 'test_wifi.py',
    'target': 'esp32',       # suite property
    'ci_job': 'nightly',     # suite property
})
print(logger.get_config())   # known attrs + properties
```

Process-wide defaults apply to every new `XunitLogger` instance.
`set_default_config()` **merges** into the existing defaults (omitted keys
are kept); call `clear_default_config()` first if you need a clean slate.
Explicit constructor arguments win over defaults; `set_config()` on an
instance only affects that instance:

```python
XunitLogger.set_default_config({
    'package': 'lab-framework',
    'hostname': 'rack-a',
    'target': 'esp32c5',     # becomes a suite property on each new logger
})

logger = XunitLogger('./xunit_report', suite_name='wifi-suite')
# package/hostname/target come from defaults; suite_name from the constructor
assert logger.get_config()['package'] == 'lab-framework'

XunitLogger.clear_default_config()   # reset for later tests / other runners
# XunitLogger.get_default_config() returns a copy of the current defaults
```

## Attaching performance details

A case can carry structured performance data via `ResultDetail`.
`add_case_detail()` attaches the detail to the running case and immediately
saves it as JSON next to the report; the relative path is recorded on the
case so it is auto-loaded when the report is parsed back.

```python
from esptest.testcase.result import ResultDetail

logger.begin_case('test_tcp_tx_throughput', classname='iperf.tcp')
logger.add_case_detail(
    ResultDetail(
        type='throughput',
        context='iperf tcp tx',
        params={'proto': 'tcp', 'direction': 'tx'},
        result={'throughput_mbps': 94.2, 'unit': 'Mbits/sec'},
        brief_message='tcp tx 94.2 Mbits/sec',
    )
)
logger.end_case()
```

`add_case_detail()` requires a running case (it raises `RuntimeError`
otherwise) and returns the same `ResultDetail` for chaining. The file is saved
at `detail.file` (relative to the report directory). When `detail.file` is
empty, a path is auto-generated as `case_details/{n}.json` (and written back
onto `detail.file`), where `n` comes from a counter that keeps incrementing
across every case in the run (so generated names never collide). Set `file`
yourself to control the path instead:

Each `ResultDetail` instance may only be passed to `add_case_detail()` once;
construct a new `ResultDetail` for every call instead of mutating and
re-adding the same object, otherwise the second call raises `ValueError`
(reusing the instance would otherwise silently overwrite the file already
saved for it).

```python
logger.add_case_detail(
    ResultDetail(
        type='throughput',
        result={'throughput_mbps': 94.2},
        file='result_details/test_tcp_tx_throughput.json',
    )
)
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
