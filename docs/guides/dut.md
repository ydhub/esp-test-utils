# Working with DUTs

A **DUT** ("device under test") wraps a serial connection and exposes a small,
consistent API for writing commands and waiting for expected output. The entry
point is `dut_wrapper`, which adapts several input types into a `DutBase`
object.

## Creating a DUT

`dut_wrapper` accepts different kinds of input:

```python
from serial import Serial

from esptest.all import DutConfig, dut_wrapper

# 1. From an already-open pyserial connection
ser = Serial('/dev/ttyUSB0', 115200, timeout=0.01)
dut = dut_wrapper(ser, name='DUT', log_file='./dut_logs/dut.log')

# 2. From a device path string
dut = dut_wrapper('/dev/ttyUSB0', name='DUT')

# 3. From a DutConfig (most flexible)
config = DutConfig(name='DUT', device='/dev/ttyUSB0', baudrate=115200)
dut = dut_wrapper(config)
```

Use it as a context manager so the port and the background reader thread are
released when the block exits:

```python
with dut_wrapper(ser, 'DUT', './dut_logs/dut.log') as dut:
    ...
```

## Sending data and matching output

```python
import re

with dut_wrapper(ser, 'DUT') as dut:
    dut.flush_data()                 # drop buffered output
    dut.write('restart\r\n')         # raw write
    dut.write_line('reboot', end='\r\n')  # write + line ending

    # str/bytes pattern: waits for the text, returns None
    dut.expect('main_task: Returned from app_main', timeout=5)

    # compiled pattern: returns the re.Match object
    match = dut.expect(re.compile(r'offset (0x\w+)'), timeout=5)
    print(match.group(1))
```

Reading buffered data directly:

```python
text = dut.read_all_data()     # decoded str, flushes by default
raw = dut.read_all_bytes()     # bytes, keeps the cache by default
cache = dut.data_cache         # current cache without flushing
```

If `expect` does not find the pattern within `timeout` seconds it raises
`TimeoutError`.

## Configuring a DUT with `DutConfig`

`DutConfig` is a dataclass describing how the DUT should be created. Commonly
used fields:

| Field            | Purpose                                                     |
| ---------------- | ----------------------------------------------------------- |
| `name`           | DUT name (defaults to the device/port base name)            |
| `device`         | Serial device, e.g. `/dev/ttyUSB0`, `COM3`                  |
| `baudrate`       | Console baudrate (0 = derive from bin path or default 115200)|
| `serial_configs` | Extra pyserial kwargs, e.g. `{'timeout': 0.1}`              |
| `bin_path`       | Firmware path; used to derive chip/stub/baudrate            |
| `log_file`       | Log file path (auto-generated under `log_path` if empty)    |
| `monitors`       | List of `DataMonitor` objects attached to the port          |
| `pexpect_timeout`| Default timeout for `expect`                                |

```python
config = DutConfig(
    name='JAP1',
    device='/dev/ttyUSB0',
    baudrate=115200,
    serial_configs={'timeout': 0.1},
)
with dut_wrapper(config) as dut:
    dut.write_line('help', end='\r\n')
    dut.expect('ready', timeout=5)
```

## Custom DUT classes

You can attach mixins by passing a custom class to `wrap_cls`. It must derive
from the DUT interface:

```python
from esptest.adapter.dut.esp_dut import EspDut

class MyDut(EspDut):
    def hello(self) -> None:
        self.write_line('hello')

with dut_wrapper(config, wrap_cls=MyDut) as dut:
    dut.hello()
```

## Attaching monitors

Pass `DataMonitor` instances through `DutConfig.monitors` to react to output as
it streams in (for example capturing a reset reason). See
{doc}`data_monitor` for the full pattern.
