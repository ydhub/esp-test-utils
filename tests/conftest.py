# ``pytest_plugins`` must live in a top-level conftest (loaded before configure);
# ``pytester`` powers the tests under ``tests/pytest_plugin/``.
pytest_plugins = ['pytester']
