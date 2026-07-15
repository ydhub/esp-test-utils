"""Run the example tests with pytest and generate one xUnit report via XunitLogger.

Instead of pytest's built-in ``--junitxml``, this example uses a session-level
:class:`~esptest.testcase.xunit.XunitLogger` (wired up in ``conftest.py``) to
capture *every* case -- both the plain function case and the ``EspTestCase``
subclass -- into a single report::

    example/pytest_xunit/pytest_xunit_output/XUNIT_RESULT.xml

Usage::

    python example/pytest_xunit/run_example.py

Or run pytest directly (the report is written by conftest, no --junitxml)::

    pytest example/pytest_xunit/test_examples.py --target esp32 -o addopts=
"""

import glob
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
# Ensure the in-repo ``esptest`` (incl. the pytest_plugin subpackage) is importable
# even when the package is not installed / editable-installed in this environment.
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pytest  # noqa: E402  # pylint: disable=wrong-import-position
from conftest import OUTPUT_DIR  # noqa: E402  # pylint: disable=import-error,wrong-import-position


def main() -> int:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    args = [
        os.path.join(HERE, 'test_examples.py'),
        '--target',
        'esp32',
        # drop the repository-wide addopts (e.g. --cov) so the example is standalone
        '-o',
        'addopts=',
        # keep any plugin-created session dir inside OUTPUT_DIR instead of the repo root
        '--rootdir',
        OUTPUT_DIR,
        '-p',
        'no:cacheprovider',
        '-v',
    ]

    logging.critical('Running: pytest %s', ' '.join(args))
    ret = pytest.main(args)
    # One case fails on purpose, so a non-zero return code is expected here.
    logging.critical('pytest finished with exit code %s (a demo failure is expected)', int(ret))

    for report in sorted(glob.glob(os.path.join(OUTPUT_DIR, '*.xml'))):
        logging.critical('XunitLogger report: %s', report)
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.CRITICAL, format='%(message)s')
    raise SystemExit(main())
