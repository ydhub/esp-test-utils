"""Custom hook specifications exposed by the esptest pytest plugin."""

import pytest

import esptest.common.compat_typing as t


@pytest.hookspec
def pytest_esptest_export_case(  # pylint: disable=unused-argument
    item: t.Any,
    case: t.Dict[str, t.Any],
    config: t.Any,
) -> None:
    """Customize a single exported case dict (used by ``--export-cases``).

    Implement this in your ``conftest.py`` to add repository-specific fields
    (e.g. ``sdk``, ``app_name``) or override the generic values in ``case``.
    The ``case`` dict is mutated in place; the return value is ignored.

    ``case`` starts with the generic fields::

        name, target, config, env, module, category, summary, timeout,
        est_time, file
    """
