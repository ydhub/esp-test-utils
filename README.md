# ESP Test Utils

This project provides some utility methods sharing between different ESP test frameworks.

## Installation

Package `esp-test-utils` is published to PyPI. Please install it via `pip`.

### Quick Start

- `pip install esp-test-utils`
- Create a file `test.py`

  ```python
  from esp_test_utils.devices.SerialTools import get_all_serial_ports

  print('All serial ports on this computer:')
  for p in get_all_serial_ports():
      print(f'  device: {p.device}, location: {p.location}')
  ```
- Run the script with `python test.py`, all connected serial devices will be shown:

  ```text
  All serial ports on this computer:0
    port: /dev/ttyUSB0, location: 1-11.4.1
  ```
- See more examples under [examples](https://github.com/espressif/pytest-embedded/tree/main/examples)

## Contributing

📘 If you are interested in contributing to this project, see the [project Contributing Guide](CONTRIBUTING.md).
