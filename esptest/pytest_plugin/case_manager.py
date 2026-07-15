"""Generic test-case management hooks for esp test repositories.

Provides CLI options to filter and export collected cases:

- ``--env NAME``                 only run cases marked ``@pytest.mark.env(NAME)``
- ``--target TARGET``            only run cases marked for TARGET (defined here only
                                 when no other plugin already provides ``--target``)
- ``--export-case-names FILE``   dump ``<target>.<config>.<case>`` names, then exit
- ``--export-cases FILE``        dump cases with metadata (json/yaml), then exit
- ``--run-case-file FILE``       only run cases whose name is listed in FILE

Repository-specific export fields are added via the
:func:`~esptest.pytest_plugin.hookspecs.pytest_esptest_export_case` hook.
"""

import argparse
import json
import logging

import pytest

import esptest.common.compat_typing as t

from .helpers import (
    DEFAULT_CASE_TIMEOUT,
    item_config,
    item_envs,
    item_est_time,
    item_exec_time,
    item_file,
    item_targets,
)

logger = logging.getLogger(__name__)

_case_manager_key = pytest.StashKey()  # type: ignore[var-annotated]


def pytest_addhooks(pluginmanager: pytest.PytestPluginManager) -> None:
    from . import hookspecs

    pluginmanager.add_hookspecs(hookspecs)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup('esptest')
    group.addoption('--env', help='only run tests matching the environment NAME.')
    group.addoption(
        '--export-case-names',
        help='collect all case names (the JUnit "name" attribute, '
        '<target>.<config>.<case_name>) into the given file, then exit without running.',
    )
    group.addoption(
        '--export-cases',
        help='collect all cases with metadata into the given file, then exit without running. '
        'The format is chosen by extension: ".yaml"/".yml" for YAML, otherwise JSON.',
    )
    group.addoption(
        '--run-case-file',
        help='only run cases whose name (<target>.<config>.<case_name>) is listed in the given '
        'file. Blank lines and lines starting with "#" are ignored; only cases matching the '
        'current --target are selected.',
    )
    # ``--target`` may already be provided by another plugin (e.g. pytest-embedded);
    # only define it here when it is missing so both setups work.
    try:
        group.addoption('--target', help='run tests for the given chip target.')
    except (ValueError, argparse.ArgumentError):
        logger.debug('--target already registered by another plugin; reusing it.')


def register_case_manager(config: pytest.Config) -> None:
    """Register markers and the :class:`EsptestCaseManager` on ``config``.

    This is intentionally *not* a ``pytest_configure`` hook: the plugin no longer
    wires up the case manager automatically. Call this from your own
    ``pytest_configure`` (see ``example/pytest_xunit/conftest.py``) to opt in.
    """
    for marker in (
        'target(names): chip target(s) this case supports.',
        'env(name): test environment this case requires.',
        'config(name): build/config label for this case.',
        'est_time(seconds): estimated run time, used by --export-cases.',
        'timeout(seconds): per-case timeout (also honored by pytest-timeout).',
    ):
        config.addinivalue_line('markers', marker)

    export_case_names = config.getoption('export_case_names', None)
    export_cases = config.getoption('export_cases', None)
    if export_case_names or export_cases:
        # only collect, never run, and do not require a single --target
        config.option.collectonly = True

    manager = EsptestCaseManager(
        target=config.getoption('target', None),
        env_name=config.getoption('env', None),
        export_case_names=export_case_names,
        export_cases=export_cases,
        run_case_file=config.getoption('run_case_file', None),
    )
    config.stash[_case_manager_key] = manager
    config.pluginmanager.register(manager)


def unregister_case_manager(config: pytest.Config) -> None:
    """Undo :func:`register_case_manager`. Call from your ``pytest_unconfigure``."""
    manager = config.stash.get(_case_manager_key, None)
    if manager is not None:
        del config.stash[_case_manager_key]
        config.pluginmanager.unregister(manager)


class EsptestCaseManager:
    """Filter and/or export collected test cases based on CLI options."""

    def __init__(
        self,
        *,
        target: t.Optional[str] = None,
        env_name: t.Optional[str] = None,
        export_case_names: t.Optional[str] = None,
        export_cases: t.Optional[str] = None,
        run_case_file: t.Optional[str] = None,
    ) -> None:
        self.target = target
        self.env_name = env_name
        self.export_case_names = export_case_names
        self.export_cases = export_cases
        self.run_case_file = run_case_file

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionstart(self, session: pytest.Session) -> None:
        if self.target:
            self.target = self.target.lower()
            session.config.option.target = self.target

    def _export_case_names(self, items: t.List[t.Any]) -> None:
        assert self.export_case_names is not None
        case_names: t.Set[str] = set()
        for item in items:
            config = item_config(item)
            for target in item_targets(item):
                case_names.add(f'{target}.{config}.{item.originalname}')
        sorted_names = sorted(case_names)
        with open(self.export_case_names, 'w', encoding='utf-8') as file:
            file.write('\n'.join(sorted_names))
            if sorted_names:
                file.write('\n')
        logger.info('Exported %d case names to %s', len(sorted_names), self.export_case_names)

    def _build_case(self, item: t.Any, target: str, config: str) -> t.Dict[str, t.Any]:
        envs = item_envs(item)
        return {
            'name': f'{target}.{config}.{item.originalname}',
            'target': 'MIXED' if '|' in target else target.upper(),
            'config': config,
            'env': envs[0] if envs else '',
            'module': 'esptest',
            'category': 'esptest',
            'summary': item.originalname,
            'timeout': item_exec_time(item),
            'est_time': item_est_time(item),
            'file': item_file(item, str(item.config.rootpath)),
        }

    def _export_cases(self, items: t.List[t.Any], config_obj: pytest.Config) -> None:
        assert self.export_cases is not None
        cases: t.List[t.Dict[str, t.Any]] = []
        for item in items:
            config = item_config(item)
            for target in item_targets(item):
                case = self._build_case(item, target, config)
                # let repositories add/override fields (e.g. sdk, app_name)
                config_obj.hook.pytest_esptest_export_case(item=item, case=case, config=config_obj)
                cases.append(case)
        cases.sort(key=lambda c: c['name'])
        export_dict = {'cases': cases}

        if self.export_cases.endswith(('.yaml', '.yml')):
            import yaml

            with open(self.export_cases, 'w', encoding='utf-8') as file:
                yaml.safe_dump(export_dict, file, allow_unicode=True, sort_keys=False)
        else:
            with open(self.export_cases, 'w', encoding='utf-8') as file:
                json.dump(export_dict, file, indent=2, ensure_ascii=False)
                file.write('\n')
        logger.info('Exported %d cases to %s', len(cases), self.export_cases)

    def _filter_by_case_file(self, items: t.List[t.Any]) -> None:
        assert self.run_case_file is not None
        with open(self.run_case_file, encoding='utf-8') as file:
            wanted = {line.strip() for line in file if line.strip() and not line.startswith('#')}

        matched: t.Set[str] = set()
        selected: t.List[t.Any] = []
        for item in items:
            name = f'{self.target}.{item_config(item)}.{item.originalname}'
            if name in wanted:
                selected.append(item)
                matched.add(name)
        items[:] = selected

        wanted_this_target = {n for n in wanted if n.startswith(f'{self.target}.')}
        missing = sorted(wanted_this_target - matched)
        if missing:
            logger.warning(
                '%d case(s) listed in %s were not found for target %s: %s',
                len(missing),
                self.run_case_file,
                self.target,
                missing,
            )
        logger.info('Selected %d case(s) from %s', len(selected), self.run_case_file)

    def pytest_collection_modifyitems(self, config: pytest.Config, items: t.List[t.Any]) -> None:
        if self.export_case_names:
            self._export_case_names(items)
            return
        if self.export_cases:
            self._export_cases(items, config)
            return

        # apply a default timeout to every case lacking an explicit one
        for item in items:
            if 'timeout' not in item.keywords:
                item.add_marker(pytest.mark.timeout(DEFAULT_CASE_TIMEOUT))

        if self.target:
            items[:] = [item for item in items if self.target in item_targets(item)]

        if self.env_name:
            items[:] = [item for item in items if self.env_name in item_envs(item)]

        if self.run_case_file:
            self._filter_by_case_file(items)
