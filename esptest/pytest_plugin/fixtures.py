"""Generic, reusable pytest fixtures for esp test repositories.

Enable them by referencing the plugin from your ``conftest.py``::

    pytest_plugins = ['esptest.pytest_plugin']

None of these fixtures depend on ``pytest-embedded``.
"""

import logging
import os
from datetime import datetime

import pytest

import esptest.common.compat_typing as t

from .helpers import item_config, resolve_target

logger = logging.getLogger(__name__)


@pytest.fixture(scope='session')
def session_tempdir(request: pytest.FixtureRequest) -> str:
    """A per-session log directory: ``<rootdir>/pytest_log/<YYYY-mm-dd_HH-MM-SS>``."""
    root = str(getattr(request.config, 'rootpath', None) or request.config.rootdir)
    tempdir = os.path.join(root, 'pytest_log', datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))
    os.makedirs(tempdir, exist_ok=True)
    return tempdir


@pytest.fixture
def log_performance(
    record_property: t.Callable[[str, object], None],
) -> t.Callable[[str, str], None]:
    """Log a performance item and record it under the JUnit ``properties`` tag."""

    def real_func(item: str, value: str) -> None:
        logging.info('[Performance][%s]: %s', item, value)
        record_property(item, value)

    return real_func


@pytest.fixture
def config(request: pytest.FixtureRequest) -> str:
    """Config label from the ``@pytest.mark.config(...)`` marker (``'Default'`` if absent)."""
    return item_config(request.node)


@pytest.fixture
def test_case_name(request: pytest.FixtureRequest, config: str) -> str:  # pylint: disable=redefined-outer-name
    """Canonical case name ``<target>.<config>.<case_name>`` (JUnit ``name`` attribute)."""
    target = resolve_target(request.config, request.node)
    original_name = getattr(request.node, 'originalname', None) or request.node.name
    return f'{target}.{config}.{original_name}'


@pytest.fixture(autouse=True)
def junit_properties(
    test_case_name: str,  # pylint: disable=redefined-outer-name
    record_xml_attribute: t.Callable[[str, object], None],
) -> None:
    """Rewrite the JUnit report case name to ``<target>.<config>.<case_name>``."""
    record_xml_attribute('name', test_case_name)


@pytest.fixture(scope='class', autouse=True)
def bind_case_context(  # pylint: disable=redefined-outer-name
    request: pytest.FixtureRequest, session_tempdir: str
) -> None:
    """Inject ``target`` / ``config`` / ``xunit_log_dir`` onto the ``TestCase`` class.

    Class-scoped fixtures cannot depend on the function-scoped ``config`` /
    ``target`` fixtures, so read them from the CLI option and markers instead.
    This pairs with :class:`esptest.testcase.EspTestCase`.
    """
    if request.cls is None:
        return
    request.cls.target = resolve_target(request.config, request.node)
    config_markers = list(request.node.iter_markers(name='config'))
    request.cls.config = config_markers[0].args[0] if config_markers else 'Default'
    request.cls.xunit_log_dir = session_tempdir
