import importlib
import os
from contextlib import contextmanager
from typing import Dict, Generator


@contextmanager
def override_env(env: Dict[str, str]) -> Generator[None, None, None]:
    saved = os.environ.copy()
    try:
        for k, v in env.items():
            os.environ[k] = v
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _reload_global_config():  # type: ignore[no-untyped-def]
    import esptest.config.global_config as gc

    return importlib.reload(gc)


def test_global_config_defaults() -> None:
    gc = _reload_global_config()
    assert gc.g.PORT_EXPECT_TIMEOUT == 30
    assert gc.g.DATA_CACHE_SIZE_LIMIT == 1 * 1024 * 1024
    assert gc.g.PORT_SPAWN_MAXREAD == 10 * 1024


def test_global_config_env_override() -> None:
    env = {
        'ESPTEST_PORT_EXPECT_TIMEOUT': '60',
        'ESPTEST_DATA_CACHE_SIZE_LIMIT': '2048',
        'ESPTEST_PORT_SPAWN_MAXREAD': '512',
    }
    with override_env(env):
        gc = _reload_global_config()
        assert gc.g.PORT_EXPECT_TIMEOUT == 60
        assert gc.g.DATA_CACHE_SIZE_LIMIT == 2048
        assert gc.g.PORT_SPAWN_MAXREAD == 512
    # Restore module-level constants back to defaults for other tests
    gc = _reload_global_config()
    assert gc.g.PORT_EXPECT_TIMEOUT == 30
    assert gc.g.DATA_CACHE_SIZE_LIMIT == 1 * 1024 * 1024
    assert gc.g.PORT_SPAWN_MAXREAD == 10 * 1024
