"""Parse the generated xUnit XML into a test-results YAML manifest.

This complements ``run_example.py``: after a run produces
``pytest_xunit_output/XUNIT_RESULT.xml`` (via :class:`XunitLogger`), this script
reads it back with :func:`esptest.testcase.xunit.parse_xunit_xml` and emits a
YAML manifest suitable for importing test results elsewhere.

Unlike a raw junit file, esptest reports carry a real per-case ``started_at`` and
``time`` (duration), plus optional ``result_details`` (loaded from the ``.json``
files referenced by each case), so this script can map them directly.

Usage::

    # default: read pytest_xunit_output/XUNIT_RESULT.xml, write test_results.yaml
    python example/pytest_xunit/xml_to_yaml.py

    # explicit input / output
    python example/pytest_xunit/xml_to_yaml.py path/to/XUNIT_RESULT.xml -o out.yaml
"""

import argparse
import logging
import os
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
# Make the in-repo ``esptest`` importable even when it is not installed.
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import yaml  # noqa: E402  # pylint: disable=wrong-import-position

import esptest.common.compat_typing as t  # noqa: E402  # pylint: disable=wrong-import-position
from esptest.common.timestamp import (  # noqa: E402  # pylint: disable=wrong-import-position
    parse_timestamp,
    timestamp_iso,
)
from esptest.testcase.xunit import (  # noqa: E402  # pylint: disable=wrong-import-position
    XUNIT_RESULT_FILE_NAME,
    parse_xunit_xml,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(HERE, 'pytest_xunit_output')
DEFAULT_XML = os.path.join(OUTPUT_DIR, XUNIT_RESULT_FILE_NAME)

_KNOWN_STATUS = {'passed', 'failed', 'error', 'skipped'}


def _normalize_status(status: t.Any) -> str:
    text = str(status or '').lower()
    return text if text in _KNOWN_STATUS else 'error'


def _to_iso(value: t.Optional[str]) -> t.Optional[str]:
    """Return a normalized ISO timestamp, or ``None`` if it cannot be parsed."""
    if not value:
        return None
    try:
        return timestamp_iso(parse_timestamp(value))
    except ValueError:
        return value


def _result_detail_to_payload(detail: t.Any) -> t.Dict[str, t.Any]:
    data = detail.to_dict() if hasattr(detail, 'to_dict') else dict(detail)
    payload: t.Dict[str, t.Any] = {
        'type': data.get('type', ''),
        'params': data.get('params') or {},
        'result': data.get('result') or {},
    }
    for key in ('brief_message', 'started_at', 'finished_at'):
        if data.get(key):
            payload[key] = data[key]
    return payload


def _case_started_at(case: t.Any, fallback: t.Optional[datetime]) -> t.Optional[str]:
    """Prefer the case's own ``started_at``; otherwise use the running fallback
    (suite timestamp + cumulative durations) so cases stay ordered in time."""
    if getattr(case, 'started_at', None):
        return _to_iso(case.started_at)
    return timestamp_iso(fallback) if fallback is not None else None


def xunit_to_manifest(xml_path: t.Union[str, Path]) -> t.Dict[str, t.Any]:
    xml_path = Path(xml_path)
    suites = parse_xunit_xml(xml_path, load_result_details=True)

    results: t.List[t.Dict[str, t.Any]] = []
    for suite in suites.test_suites:
        suite_started = None
        suite_timestamp = getattr(suite, 'timestamp', None)
        if suite_timestamp:
            try:
                suite_started = parse_timestamp(suite_timestamp)
            except ValueError:
                suite_started = None
        hostname = (getattr(suite, 'hostname', None) or '').strip() or socket.gethostname()

        elapsed = timedelta()
        for case in suite.test_cases:
            duration_s = float(getattr(case, 'duration', 0) or 0)
            fallback = suite_started + elapsed if suite_started is not None else None
            started_at = _case_started_at(case, fallback)
            elapsed += timedelta(seconds=duration_s)

            status = _normalize_status(case.status)
            brief = None
            if status in ('failed', 'error'):
                brief = (case.message or '').strip() or None

            results.append(
                {
                    'case_key': case.name,
                    'status': status,
                    'duration': round(duration_s, 3),
                    'started_at': started_at,
                    'runner_hostname': hostname,
                    'brief_message': brief,
                    'details': [_result_detail_to_payload(d) for d in (case.result_details or [])],
                }
            )

    return {
        'schema_version': 1,
        'kind': 'esptest.test_results',
        'generated_at': timestamp_iso(),
        'results': results,
    }


def convert(xml_path: t.Union[str, Path], out_path: t.Union[str, Path]) -> Path:
    manifest = xunit_to_manifest(xml_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=120)
    out_path.write_text(text, encoding='utf-8')
    return out_path


def main(argv: t.Optional[t.List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        'xml_path',
        nargs='?',
        default=DEFAULT_XML,
        help=f'path to the xUnit XML report (default: {DEFAULT_XML}).',
    )
    parser.add_argument(
        '-o',
        '--output',
        default=None,
        help='output YAML path (default: <xml_dir>/test_results.yaml).',
    )
    args = parser.parse_args(argv)

    xml_path = Path(args.xml_path)
    if not xml_path.is_file():
        logger.error('xUnit report not found: %s (run run_example.py first)', xml_path)
        return 1

    out_path = Path(args.output) if args.output else xml_path.with_name('test_results.yaml')
    written = convert(xml_path, out_path)

    manifest = xunit_to_manifest(xml_path)
    logger.info('Wrote %s (%d case results)', written, len(manifest['results']))
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    raise SystemExit(main())
