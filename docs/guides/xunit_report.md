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
`RuntimeError`. Key `running` (see `XunitLogger.RESERVED_CASE_PROPERTY_KEYS`)
raises `ValueError`. `failure_type` / `known_issue` are not reserved yet for
backward compatibility — prefer `set_failure_type` / `set_known_issue`.
Subclasses may override the reserved set. It does not flush immediately—the
properties are written by a later periodic or explicit flush, or when
`end_case()` finishes the case.

`end_case(result=False, ...)` records a failure via `add_failure` (no-op if
the case is already ERROR); `add_skipped` marks it SKIPPED.

`begin_case` records `TestCaseResult.started_at` (ISO timestamp). On write it
becomes the `<testcase timestamp="...">` attribute (not a case property).
`parse_xunit_xml` maps that attribute back to `started_at`, and still accepts
legacy reports that stored it as property `started_at` (attribute wins if both
are present).

While a case is open, periodic/`force` flushes snapshot it with
`TestCaseStatus.RUNNING` and property `running=true` (no `<failure>` /
`<error>` child). `parse_xunit_xml` defaults to `keep_running=False`, so
final/CI readers see those cases as `ERROR`. Pass `keep_running=True`
for live mid-run monitors that need `RUNNING`. Legacy reports that used
`<error message="Test case is still running">` follow the same flag.

## Public API reference (`XunitLogger`)

This section lists the stable instance / class APIs most runners need. Full
signatures live in the Sphinx API pages generated from
`esptest.testcase.xunit`.

### Case lifecycle

| API | Role |
| --- | --- |
| `begin_case(case_id, classname='', category=None)` | Start a case. If one was already open, it is closed as ERROR via `close(...)` first. Optional `category` is stored as a case property. |
| `end_case(result=True, message='', failure_type='')` | Finish the running case (duration + stdout/stderr), append it to the suite, and flush. `result=False` records a failure via `add_failure` (no-op if the case is already ERROR). |
| `close(message=...)` | Force-finish a still-running case as ERROR (e.g. runner teardown / interrupt), then flush. |
| `flush(force=False)` | Write the XML report. Without `force=True`, writes are rate-limited by `flush_interval`. |

### Current / last case

| API | Returns | Notes |
| --- | --- | --- |
| `running_case` | `TestCaseResult` or `None` | The case started by `begin_case` and not yet finished by `end_case` / `close`. Prefer this when you need “what is running **right now**”. |
| `has_running_case` | `bool` | `True` iff `running_case is not None`. |
| `current_test_case` | `TestCaseResult` or `None` | `running_case` if set; otherwise the **last finished** case in the suite. Handy after `end_case` when you still want the just-closed result. |
| `get_cur_case_id()` | `str` | Name of `current_test_case`, or `''` if none. |
| `get_cur_case_result()` | `(ok: bool, message: str)` | `ok` is `False` when `current_test_case` is FAILED or ERROR. |

```python
logger.begin_case('test_assoc', classname='wifi.station')
assert logger.has_running_case
assert logger.running_case is not None
assert logger.get_cur_case_id() == 'test_assoc'

logger.add_failure('assoc timeout', fail_type='timeout')
ok, msg = logger.get_cur_case_result()
assert ok is False and 'assoc timeout' in msg

logger.end_case()
assert logger.running_case is None
# current_test_case falls back to the case just finished:
assert logger.current_test_case is not None
assert logger.current_test_case.name == 'test_assoc'
```

### Recording status and output

| API | Role |
| --- | --- |
| `add_sys_out(message)` / `add_sys_err(message)` | Append to case stdout / stderr (bounded head+tail). Before `begin_case`, text is buffered and prepended to the next case. |
| `add_failure(message, fail_type=...)` | Mark the **running** case FAILED (may be called before `end_case`). No-op if the case is already ERROR. |
| `add_error(message)` | Mark the running case ERROR. |
| `add_skipped(message='')` | Mark the running case SKIPPED. |
| `clear_failures()` | Reset the running case back to PASSED and clear its message. |
| `set_case_properties(properties)` | Merge string properties into the running case. Rejects reserved key `running` (subclass-overridable). |
| `set_known_issue(reason='')` | Set property `known_issue` to `reason` or `'1'`. Readable via `TestCaseResult.known_issue`. |
| `set_failure_type(fail_type='')` | Set property `failure_type` and sync the case field (empty → `unknown`). |
| `add_case_detail(detail)` | Attach a `ResultDetail`, save its JSON next to the report, and register the relative path. |

`add_failure` / `add_error` / `add_skipped` / `clear_failures` / `set_case_properties` /
`add_case_detail` all require a running case and raise `RuntimeError` otherwise.

### Suite config

| API | Role |
| --- | --- |
| `set_config(config)` / `get_config()` | Update / read suite attrs (`suite_name`, `package`, `file`, `hostname`) and suite properties. |
| `XunitLogger.set_default_config` / `get_default_config` / `clear_default_config` | Process-wide defaults applied by every **new** instance. |

Useful attributes: `xunit_file` (report path), `test_suite` / `test_suites`
(in-memory result tree). Module helpers `generate_xunit_xml`, `save_xunit_xml`,
and `parse_xunit_xml` are covered in the sections below.

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
auto-loading any referenced `ResultDetail` JSON files. Incomplete mid-run
cases (property `running=true`) become `ERROR` by default; pass
`keep_running=True` to keep `TestCaseStatus.RUNNING`. Property `failure_type`
wins over `<failure|error type="...">`. All `<failure>` / `<error>` children
are kept on `case.xml_failure` / `case.xml_error`; when both are present,
status prefers **error** over failure. Dump (`generate_xunit_xml`) re-emits
those lists when non-empty, otherwise falls back to a single status child from
`status` / `message` / `failure_type`. `testcase` attributes `file` / `line`
round-trip on `TestCaseResult`. Property `known_issue` is exposed as
`case.known_issue`.

```python
from esptest.testcase.xunit import parse_xunit_xml

suites = parse_xunit_xml('./xunit_report/iperf_result.xml')
print(f'tests={suites.tests}, failures={suites.failures}, errors={suites.errors}')
for suite in suites.test_suites:
    for case in suite.test_cases:
        print(f'[{case.status}] {suite.name}::{case.name}')

# live monitor reading a flush while a case is still open:
live = parse_xunit_xml('./xunit_report/XUNIT_RESULT.xml', keep_running=True)
```

See `example/xunit_report.py` in the repository for a complete, runnable
walk-through.
