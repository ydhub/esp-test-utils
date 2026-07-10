# ESP Test Utils

This project provides some utility methods sharing between different ESP test frameworks.

## Installation

Package `esp-test-utils` is published to PyPI. Please install it via `pip`.

### Quick Start

- `pip install esp-test-utils`
- Create a file `test.py`

  ```python
  from esptest.devices.serial_tools import get_all_serial_ports

  print('All serial ports on this computer:')
  for p in get_all_serial_ports():
      print(f'  device: {p.device}, location: {p.location}')
  ```
- Run the script with `python test.py`, all connected serial devices will be shown:

  ```text
  All serial ports on this computer:0
    port: /dev/ttyUSB0, location: 1-11.4.1
  ```
- See more examples under [examples](https://github.com/ydhub/esp-test-utils/tree/main/example)

## Documentation

Full documentation lives under the [`docs/`](docs) directory and covers
installation, a quick start, user guides (DUT, data monitor, xUnit reporting,
CLI tools), and the auto-generated API reference.

Build the HTML site locally:

```sh
pip install -e '.[doc]'
cd docs && make html
# open docs/_build/html/index.html
```

## Contributing

📘 If you are interested in contributing to this project, see the [project Contributing Guide](CONTRIBUTING.md).
