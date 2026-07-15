"""Public marker/option readers for the esptest pytest plugin.

These helpers read a pytest item's ``target`` / ``config`` / ``env`` / ``timeout``
markers and resolve the effective target. They are reused by the plugin's own
fixtures and hooks, and are exported from :mod:`esptest.pytest_plugin` so test
repositories can reuse the exact same logic in their own conftest.
"""

import os

import esptest.common.compat_typing as t

#: default per-case timeout (seconds) applied to items without a ``timeout`` marker
DEFAULT_CASE_TIMEOUT = 5 * 60


def item_targets(item: t.Any) -> t.List[str]:
    """All (lower-cased) targets declared via ``@pytest.mark.target(...)``.

    A single marker may carry either one target or a list/tuple of targets.
    """
    targets: t.List[str] = []
    for marker in item.iter_markers(name='target'):
        assert len(marker.args) == 1, f'target marker takes exactly 1 arg (failed: {item.name})'
        value = marker.args[0]
        if isinstance(value, (list, tuple)):
            targets.extend(str(v).lower() for v in value)
        else:
            targets.append(str(value).lower())
    return targets


def item_config(item: t.Any) -> str:
    """Config label from ``@pytest.mark.config(...)``; ``'Default'`` when absent."""
    markers = list(item.iter_markers(name='config'))
    return markers[0].args[0] if markers and markers[0].args else 'Default'


def item_envs(item: t.Any) -> t.List[str]:
    """Env names from ``@pytest.mark.env(...)`` markers."""
    return [marker.args[0] for marker in item.iter_markers(name='env') if marker.args]


def item_exec_time(item: t.Any, default: int = DEFAULT_CASE_TIMEOUT) -> int:
    """Timeout (seconds) from ``@pytest.mark.timeout(...)``; ``default`` when absent."""
    markers = list(item.iter_markers(name='timeout'))
    return markers[0].args[0] if markers and markers[0].args else default


def item_est_time(item: t.Any) -> int:
    """Estimated run time (seconds) from ``@pytest.mark.est_time(...)``; ``0`` when absent."""
    markers = list(item.iter_markers(name='est_time'))
    return markers[0].args[0] if markers and markers[0].args else 0


def item_file(item: t.Any, root_dir: str = '') -> str:
    """Test file path, relative to ``root_dir`` when possible."""
    path = str(item.path)
    if root_dir:
        try:
            return os.path.relpath(path, root_dir)
        except ValueError:
            return path
    return path


def resolve_target(config: t.Any, item: t.Optional[t.Any] = None) -> str:
    """Resolve the effective target string.

    Prefer the ``--target`` CLI option; otherwise join all targets declared by
    the item's markers (``t1|t2``). Returns ``'unknown'`` when nothing is found.
    """
    target = config.getoption('target', None)
    if target:
        return str(target).lower()
    if item is not None:
        targets = sorted(set(item_targets(item)))
        if targets:
            return '|'.join(targets)
    return 'unknown'
