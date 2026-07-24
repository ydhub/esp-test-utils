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

| Field             | Purpose                                                              |
| ----------------- | -------------------------------------------------------------------- |
| `name`            | DUT name (defaults to the device/port base name)                     |
| `device`          | Log UART serial device, e.g. `/dev/ttyUSB0`, `COM3`                  |
| `baudrate`        | Console baudrate (0 = derive from bin path or default 115200)        |
| `serial_configs`  | Extra pyserial kwargs, e.g. `{'timeout': 0.1}`                       |
| `bin_path`        | Firmware path; used to derive chip/stub/baudrate                     |
| `download_device` | Flash/download UART (defaults to `device` if unset)                  |
| `support_esptool` | Enable esptool-backed `hard_reset` / `download_bin` / `get_chip_info`|
| `log_file`        | Log file path (auto-generated under `log_path` if empty)             |
| `monitors`        | List of `DataMonitor` objects attached to the port                   |
| `pexpect_timeout` | Default timeout for `expect`                                         |

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

## ESP helpers (`EspDut` / `EspMixin`)

`dut_wrapper` defaults to {class}`~esptest.adapter.dut.esp_dut.EspDut`, which
includes {class}`~esptest.adapter.dut.esp_mixin.EspMixin`. With
`support_esptool=True` you can hard-reset, flash, and read chip info.

### Same log and download port

When `download_device` is unset or equals `device`, the log UART also hosts
the persistent esptool handle (`dut.esp`):

```python
config = DutConfig(
    name='DUT',
    device='/dev/ttyUSB0',
    support_esptool=True,
    bin_path='./build',
)
with dut_wrapper(config) as dut:
    info = dut.get_chip_info()
    print(info.chip_name, info.chip_rev_full, info.mac)
    dut.hard_reset()
    dut.download_bin()
```

`get_chip_info()` returns an
{class}`~esptest.devices.esp_serial.EspPortInfo`. `chip_rev_full` is
`major * 100 + minor` (same scale as bootloader `min_rev_full` /
`max_rev_full`); `-1` means unknown. Successful detections are cached on the
DUT instance.

### Separate download and log UARTs

Some boards expose two UARTs: one for console logging and another for
download / flash. Set both ports and keep `support_esptool=True`:

```python
config = DutConfig(
    name='DUT',
    device='/dev/ttyUSB0',           # log UART
    download_device='/dev/ttyUSB1',  # flash / reset UART
    support_esptool=True,
    bin_path='./build',
    # optional: download_serial_configs={'timeout': 0.01, 'baudrate': 115200}
    # optional: save_download_log=False  # disable download-port side log
)
with dut_wrapper(config) as dut:
    # Log port stays a plain serial port (dut.esp is None).
    # hard_reset / download_bin / get_chip_info use download_device.
    # Dual-UART also opens a side SerialPort on download_device and saves
    # RX + esptool output to <dut_log_stem>_download.log by default.
    dut.hard_reset()
    info = dut.get_chip_info()
    dut.download_bin()
```

Invariant: `dut.esp` is only set when the log port is the same serial device
as `download_device` (or download is unset). Separate ports still allow
esptool operations through `download_device`.

A runnable sample is `jap_test_dual_uart_download_bin` in
`example/jap_test.py`.

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
