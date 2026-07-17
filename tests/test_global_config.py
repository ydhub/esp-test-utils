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
    assert gc.g.SKIP_ESPTOOL_DETECT_VID_PID == frozenset([(0x303A, 0x4001)])


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


def test_parse_skip_esptool_detect_vid_pid() -> None:
    from esptest.config.global_config import parse_skip_esptool_detect_vid_pid

    assert parse_skip_esptool_detect_vid_pid(None) == frozenset([(0x303A, 0x4001)])
    assert parse_skip_esptool_detect_vid_pid('') == frozenset()
    assert parse_skip_esptool_detect_vid_pid('none') == frozenset()
    assert parse_skip_esptool_detect_vid_pid('OFF') == frozenset()
    assert parse_skip_esptool_detect_vid_pid('303a:4001,10c4:ea60') == frozenset([(0x303A, 0x4001), (0x10C4, 0xEA60)])
    assert parse_skip_esptool_detect_vid_pid('0x303A:0x4001') == frozenset([(0x303A, 0x4001)])


def test_skip_esptool_detect_vid_pid_env_disable() -> None:
    with override_env({'ESPTEST_SKIP_ESPTOOL_DETECT_VID_PID': 'none'}):
        gc = _reload_global_config()
        assert gc.g.SKIP_ESPTOOL_DETECT_VID_PID == frozenset()
    _reload_global_config()


def test_skip_esptool_detect_vid_pid_env_replace() -> None:
    with override_env({'ESPTEST_SKIP_ESPTOOL_DETECT_VID_PID': '10c4:ea60'}):
        gc = _reload_global_config()
        assert gc.g.SKIP_ESPTOOL_DETECT_VID_PID == frozenset([(0x10C4, 0xEA60)])
    _reload_global_config()
