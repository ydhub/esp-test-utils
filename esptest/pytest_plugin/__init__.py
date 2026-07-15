"""Reusable pytest plugin for esp test repositories.

This is an *importable* plugin: it is **not** registered via a ``pytest11``
entry point, so nothing changes until you opt in from your ``conftest.py``::

    pytest_plugins = ['esptest.pytest_plugin']

It then provides:

- generic fixtures (``session_tempdir``, ``log_performance``, ``config``,
  ``test_case_name``, ``junit_properties``, ``bind_case_context``), and
- case-management options (``--env`` / ``--target`` filtering,
  ``--export-case-names`` / ``--export-cases`` / ``--run-case-file``) and the
  ``pytest_esptest_export_case`` hook. The case manager is **not** registered
  automatically -- call :func:`register_case_manager` /
  :func:`unregister_case_manager` from your own ``pytest_configure`` /
  ``pytest_unconfigure`` (see ``example/pytest_xunit/conftest.py``), and
- reusable marker/option readers (``item_targets``, ``item_config``,
  ``item_envs``, ``resolve_target`` ...) from :mod:`esptest.pytest_plugin.helpers`.

None of it depends on ``pytest-embedded``.
"""

from .case_manager import (
    EsptestCaseManager,
    pytest_addhooks,
    pytest_addoption,
    register_case_manager,
    unregister_case_manager,
)
from .fixtures import (
    bind_case_context,
    config,
    junit_properties,
    log_performance,
    session_tempdir,
    test_case_name,
)
from .helpers import (
    DEFAULT_CASE_TIMEOUT,
    item_config,
    item_envs,
    item_est_time,
    item_exec_time,
    item_file,
    item_targets,
    resolve_target,
)

__all__ = [
    'DEFAULT_CASE_TIMEOUT',
    'EsptestCaseManager',
    'bind_case_context',
    'config',
    'item_config',
    'item_envs',
    'item_est_time',
    'item_exec_time',
    'item_file',
    'item_targets',
    'junit_properties',
    'log_performance',
    'pytest_addhooks',
    'pytest_addoption',
    'register_case_manager',
    'resolve_target',
    'session_tempdir',
    'test_case_name',
    'unregister_case_manager',
]
