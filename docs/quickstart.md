# Quick start

This page walks through the most common first steps: discovering serial
ports and talking to a device.

## List connected serial ports

```python
from esptest.devices.serial_tools import get_all_serial_ports

print('All serial ports on this computer:')
for p in get_all_serial_ports():
    print(f'  device: {p.device}, location: {p.location}')
```

Running the script prints every connected serial device:

```text
All serial ports on this computer:
  device: /dev/ttyUSB0, location: 1-11.4.1
```

You can also resolve a device path, port name, or USB location to the real
device node:

```python
from esptest.devices.serial_tools import compute_serial_port

device = compute_serial_port('1-11.4.1')  # -> '/dev/ttyUSB0'
```

## Talk to a device

The `dut_wrapper` helper turns an existing serial connection (or a
{class}`~esptest.adapter.dut.dut_base.DutConfig`) into a DUT object with a
convenient `write` / `expect` API. It works as a context manager so the port
and its background reader thread are cleaned up automatically.

```python
import re

from serial import Serial

from esptest.all import dut_wrapper

ser = Serial('/dev/ttyUSB0', 115200, timeout=0.01)
with dut_wrapper(ser, 'DUT', './dut_logs/dut.log') as dut:
    dut.flush_data()
    dut.write('restart\r\n')
    match = dut.expect(re.compile(r'Loaded app from partition at offset (0x\w+)'), timeout=5)
    dut.expect('main_task: Returned from app_main', timeout=5)
    print('BOOT offset:', match.group(1))
```

Key points:

- Passing a `str` regex/text to `expect` waits for that text and returns
  `None`; passing a compiled `re.Pattern` returns the `re.Match` object.
- All received data is mirrored to the log file you pass as the third
  argument.

## Where to go next

- {doc}`guides/dut` — the full DUT API, `DutConfig`, and customization.
- {doc}`guides/data_monitor` — react to device output as it streams in.
- {doc}`guides/xunit_report` — record results as xUnit XML.
- {doc}`guides/cli_tools` — the bundled `esp-*` command line tools.
