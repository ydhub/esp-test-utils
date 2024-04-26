import os

import pytest

# These tests needs target Dut with specific test apps flashed.
# Skip them by default (if not supported).
RUN_TARGET_TEST = os.environ.get('RUN_TARGET_TEST')


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list) -> None:
    for item in items:
        if 'target_test' in [m.name for m in item.iter_markers()]:
            item.add_marker(pytest.mark.skipif(not RUN_TARGET_TEST, reason='Do not run target tests if not supported'))
