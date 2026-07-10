# Streaming data monitor

`DataMonitor` scans data as it arrives and fires a callback whenever a pattern
matches. It is useful for reacting to asynchronous device output — reset
reasons, chip versions, crash signatures — without polling `expect`.

## Basic usage

```python
import re

from esptest.common.data_monitor import DataMonitor, MatchedResult

RST_REASON_PATTERN = re.compile(r'rst:\s*(0x\w+\s*\(\w+\))')

def on_reset(matched: MatchedResult) -> None:
    assert isinstance(matched.match, re.Match)
    print('reset reason:', matched.match.group(1))

monitor = DataMonitor(RST_REASON_PATTERN, on_reset)

# Feed data as it is read (port_name, data, optional timestamp)
monitor.append_data('DUT', 'rst:0x1 (POWERON_RESET)\n')
```

The callback receives a {class}`~esptest.common.data_monitor.MatchedResult`
with these attributes:

- `key` — the pattern string.
- `port_name` — which port produced the data.
- `match` — the `re.Match` object (for compiled patterns) or the matched
  substring (for plain-text patterns).
- `timestamp` — when the match happened.

A monitor also keeps aggregate state you can inspect afterwards:
`matched_count`, `matched_ports`, and `matched_results`.

## Pattern types

- **Compiled `re.Pattern`** — matched with `search`; `match` is an `re.Match`.
- **Plain `str`** — matched as a literal substring; `match` is the string.

Multiple matches accumulated in a single `append_data` call are all consumed,
firing the callback once per match.

## Restricting to specific ports

Pass `port_names` to only react to data from selected ports:

```python
monitor = DataMonitor(RST_REASON_PATTERN, on_reset, port_names=['DUT', 'DUT2'])
```

Data from any other port name is ignored.

## Attaching monitors to a DUT

Monitors are most useful attached to a DUT, so they run automatically against
the live serial stream. Pass them through `DutConfig.monitors`:

```python
from esptest.all import DutConfig, dut_wrapper
from esptest.common.data_monitor import DataMonitor

chip_version = DataMonitor(re.compile(r'Chip rev:\s*(v[\d\.]+)'), on_reset)
rst_reason = DataMonitor(RST_REASON_PATTERN, on_reset)

config = DutConfig(
    name='JAP1',
    device='/dev/ttyUSB0',
    baudrate=115200,
    monitors=[chip_version, rst_reason],
)
with dut_wrapper(config) as dut:
    dut.write_line('reboot', end='\r\n')
    dut.expect('ready')
```

You can also read or replace a DUT's monitors at runtime through the
`dut.monitors` property.
