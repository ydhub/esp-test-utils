# Installation

`esp-test-utils` is published to PyPI and installed with `pip`.

## Requirements

- Python 3.7 or newer
- POSIX (Linux/macOS) or Windows

## Install from PyPI

```bash
pip install esp-test-utils
```

This installs the core dependencies needed for serial/DUT interaction,
logging, and the reporting helpers.

## Optional features (extras)

Some functionality depends on extra packages that are not installed by
default. Install the extra you need:

```bash
# IDF CI helpers (chart rendering, GitLab and MinIO clients)
pip install "esp-test-utils[idfci]"

# Everything, including esp-idf-monitor and scapy
pip install "esp-test-utils[all]"
```

| Extra    | Adds                                                       |
| -------- | ---------------------------------------------------------- |
| `idfci`  | `pyecharts`, `python-gitlab`, `minio`                      |
| `all`    | `idfci` packages plus `esp-idf-monitor` and `scapy`        |

## Development install

Clone the repository and install it in editable mode with the development
and documentation extras:

```bash
git clone https://github.com/ydhub/esp-test-utils.git
cd esp-test-utils
python -m venv venv && source ./venv/bin/activate
pip install -e ".[dev,doc]"
```

Then install the pre-commit hooks and run the test suite:

```bash
pre-commit install
pytest
```

## Building the documentation

With the `doc` extra installed, build the HTML site from the `docs/`
directory:

```bash
cd docs
make html
```

The rendered site is written to `docs/_build/html/index.html`. The API
reference stubs under `docs/api/_generated/` are regenerated automatically
by `sphinx-apidoc` each time you run `make`.
