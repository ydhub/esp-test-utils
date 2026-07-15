# pytest + XunitLogger example

This example shows how to use the reusable **esptest pytest plugin**
(`esptest.pytest_plugin`) together with `esptest.testcase` to:

- run both a plain **function** test and a **`EspTestCase`** (unittest-style) suite,
- produce **one unified xUnit report** with `XunitLogger` (no pytest `--junitxml`),
  including a real per-case `started_at` and execution `time`,
- **export** the collected cases (names / metadata), and
- **run a selected subset** of cases listed in a file.

## Files

| File | Purpose |
|------|---------|
| `conftest.py` | Enables the plugin and wires up a session-level `XunitLogger`. |
| `test_examples.py` | One function case + one `EspTestCase` subclass. |
| `run_example.py` | Runs pytest programmatically and prints the report path. |
| `xml_to_yaml.py` | Parses the generated xUnit XML into a YAML manifest. |
| `pytest_xunit_output/` | Generated output (report / YAML). Safe to delete/regenerate. |

## 1. How `conftest.py` is configured

Five pieces make the unified report work:

1. **Enable the plugin**:

   ```python
   pytest_plugins = ['esptest.pytest_plugin']
   ```

   This adds the `--target` / `--env` / export / `--run-case-file` options, the
   `pytest_esptest_export_case` hook, and generic fixtures (`session_tempdir`,
   `test_case_name`, `bind_case_context`, ...).

2. **Opt in to case filtering/export** and **open/close one shared
   `XunitLogger`** for the whole session. The plugin does *not* register the case
   manager automatically, so call `register_case_manager` yourself (this also
   registers the `target` / `config` / `env` / `timeout` markers):

   ```python
   from esptest.pytest_plugin import register_case_manager, unregister_case_manager

   def pytest_configure(config):
       register_case_manager(config)   # enable --target/--env/export/--run-case-file
       init_session_logger()           # creates XunitLogger(OUTPUT_DIR, ...)

   def pytest_unconfigure(config):
       unregister_case_manager(config)
       close_session_logger()          # flush + close -> writes XUNIT_RESULT.xml
   ```

3. **Record plain function cases** into that logger from a report hook, using
   pytest's real timing (`call.start` -> `started_at`, `call.duration` -> `time`):

   ```python
   @pytest.hookimpl(hookwrapper=True)
   def pytest_runtest_makereport(item, call):
       ...  # begin_case / end_case for non-class items on the "call" phase
   ```

4. **Hand the same logger to `EspTestCase` classes** via a class-scoped autouse
   fixture (it runs before `setUpClass`, so the class reuses the logger and
   reports itself via `setUp` / `tearDown`):

   ```python
   @pytest.fixture(scope='class', autouse=True)
   def bind_session_logger(request):
       if request.cls is not None and issubclass(request.cls, EspTestCase):
           request.cls.xunit_logger = _session_logger
   ```

Class-based cases are skipped by the `makereport` hook to avoid double counting.

> To reuse this in your own repo, copy the five pieces above into your
> `conftest.py`. The hard requirements are `pytest_plugins =
> ['esptest.pytest_plugin']` plus the `register_case_manager` /
> `unregister_case_manager` calls to enable filtering/export.

## 2. Run the tests and generate the xUnit XML

Programmatically (recommended for a quick try):

```bash
python example/pytest_xunit/run_example.py
```

Or with pytest directly (the report is written by `conftest.py`, no `--junitxml`):

```bash
pytest example/pytest_xunit --target esp32 -o addopts=
```

Notes:

- `--target esp32` selects the cases marked for `esp32` (both the function case
  and `TestExampleSuite`). Use `--target esp32s3` to run only `TestExampleSuite`,
  which also targets `esp32s3`.
- `-o addopts=` drops this repository's default `addopts` (e.g. `--cov`) so the
  example runs standalone; omit it in your own project.
- The report is written to:

  ```
  example/pytest_xunit/pytest_xunit_output/XUNIT_RESULT.xml
  ```

- One case (`test_expected_fail`) fails on purpose so the report shows a
  `FAILED` entry; the pytest exit code is therefore non-zero. Each `<testcase>`
  carries a real `started_at` property and a real `time` (execution seconds).

## 3. Export cases

Export only the case names (`<target>.<config>.<case_name>`, one per line). This
collects but does not run any test:

```bash
pytest example/pytest_xunit --export-case-names cases.txt -o addopts=
```

`cases.txt`:

```
esp32.Default.test_expected_fail
esp32.Default.test_pass
esp32.Default.test_single_function
esp32s3.Default.test_expected_fail
esp32s3.Default.test_pass
```

`TestExampleSuite` is marked `@pytest.mark.target(['esp32', 'esp32s3'])`, so each
of its cases expands into one entry per target (`esp32.*` and `esp32s3.*`), while
the `esp32`-only `test_single_function` appears just once.

Export cases with metadata (name, target, config, env, timeout, file, ...). The
format is chosen by the file extension: `.json` (default) or `.yaml` / `.yml`:

```bash
pytest example/pytest_xunit --export-cases cases.json -o addopts=
pytest example/pytest_xunit --export-cases cases.yaml -o addopts=
```

`cases.json` (excerpt):

```json
{
  "cases": [
    {
      "name": "esp32.Default.test_pass",
      "target": "ESP32",
      "config": "Default",
      "env": "generic",
      "module": "pytest",
      "category": "Function",
      "summary": "test_pass",
      "timeout": 300,
      "est_time": 0,
      "file": "example/pytest_xunit/test_examples.py"
    }
  ]
}
```

> To add repository-specific fields (e.g. `sdk`, `app_name`), implement the
> `pytest_esptest_export_case(item, case, config)` hook in your `conftest.py`
> and mutate `case` in place.

## 4. Run only the cases listed in a file

Create a file with one case name per line (blank lines and lines starting with
`#` are ignored). Only names matching the current `--target` are selected:

```bash
cat > run.txt <<'EOF'
# run just one case
esp32.Default.test_pass
EOF

pytest example/pytest_xunit --target esp32 --run-case-file run.txt -o addopts=
```

This runs only `test_pass`. The names must match the export format
(`<target>.<config>.<case_name>`), so a common workflow is:

```bash
# 1) list everything, edit the file to keep what you want
pytest example/pytest_xunit --export-case-names all_cases.txt -o addopts=

# 2) run the selected subset
pytest example/pytest_xunit --target esp32 --run-case-file all_cases.txt -o addopts=
```

## 5. Convert the xUnit XML to a YAML manifest

`xml_to_yaml.py` reads a generated report back with
`esptest.testcase.xunit.parse_xunit_xml` and emits a YAML manifest (one entry per
case, with real `status` / `duration` / `started_at` and any loaded
`result_details`):

```bash
# default: read pytest_xunit_output/XUNIT_RESULT.xml, write test_results.yaml
python example/pytest_xunit/xml_to_yaml.py

# explicit input / output
python example/pytest_xunit/xml_to_yaml.py path/to/XUNIT_RESULT.xml -o out.yaml
```

Example `pytest_xunit_output/test_results.yaml`:

```yaml
schema_version: 1
kind: esptest.test_results
generated_at: 2026-07-15T10:28:53.347191+0800
results:
- case_key: esp32.Default.test_single_function
  status: passed
  duration: 0.1
  started_at: 2026-07-15T10:28:52.607966+0800
  runner_hostname: my-host
  brief_message: null
  details: []
- case_key: esp32.Default.test_expected_fail
  status: failed
  duration: 0.001
  started_at: 2026-07-15T10:28:52.711153+0800
  runner_hostname: my-host
  brief_message: 'AssertionError: 5 != 4 : demo failure: 2 + 3 is not 4'
  details: []
```

## Option reference (from `esptest.pytest_plugin`)

| Option | Effect |
|--------|--------|
| `--target TARGET` | Only run cases marked for `TARGET`. Required for `--run-case-file`. |
| `--env NAME` | Only run cases marked `@pytest.mark.env(NAME)`. |
| `--export-case-names FILE` | Write `<target>.<config>.<case>` names to `FILE`, then exit. |
| `--export-cases FILE` | Write cases with metadata (JSON/YAML by extension), then exit. |
| `--run-case-file FILE` | Only run cases whose name is listed in `FILE`. |
