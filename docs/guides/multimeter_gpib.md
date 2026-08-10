# Multimeter — GPIB (Draft)

```{warning}
This GPIB Multimeter API is **Draft**. Signatures and behavior may change
without a deprecation period.
```

GPIB backend for Keysight-style SCPI multimeters (e.g. 34465A / 34401A), used
through the shared `Multimeter` facade (`backend='gpib'`).

**Provenance (Draft):** GPIB measure logic was initialized from ATS
(`AutoTestScript` / `comm/GPIB*`) at commit
`e10787397ad19426fd17d9b64d97f47f768da349`, then adapted into this package.

## Dependencies (install yourself)

`esp-test-utils` does **not** ship a `[gpib]` extra. Install the driver that
matches your OS / stack:

| Stack | Install |
|-------|---------|
| Windows / VISA resource strings | `pip install pyvisa` (and a VISA backend such as NI-VISA if required) |
| Linux native GPIB | System **linux-gpib** package that provides `import Gpib` (not on PyPI) |
| Linux via VISA | `pip install pyvisa` and pass `resource=` (e.g. `GPIB0::22::INSTR`) |

```bash
# Example: VISA / Windows
pip install pyvisa

# Example: Debian/Ubuntu style linux-gpib (package names vary by distro)
# sudo apt install ...   # must provide Python module `Gpib`
```

`open_gpib` on Linux prefers native `Gpib` when only `address=` is given. Pass
`resource=` to force pyvisa on Linux as well.

Missing drivers raise a clear `ImportError` telling you what to install.

## Discovering instruments

```python
from esptest.devices.multimeter import get_multimeter_specific, list_multimeters

for info in list_multimeters(backend='gpib'):
    print(info.backend, info.address, info.resource, info.identity)

# Fail unless exactly one device matches
mm = get_multimeter_specific(backend='gpib', address=22)
# or: resource='GPIB0::22::INSTR'
```

Filters:

| Parameter | Meaning |
|-----------|---------|
| `address` | GPIB primary address (`int`), typical on Linux |
| `resource` | VISA resource string |
| `serial_number` / `path` | Reserved for Joulescope — raise `NotImplementedError` on GPIB |

When multiple backends are registered and more than one returns devices, pass
`backend=` explicitly or `list_multimeters` raises `RuntimeError`.

A device is only reported when it answers `*IDN?`. An openable GPIB handle with
no identity reply is skipped, so discovery does not report bus addresses that
carry no DMM.

## Measuring current

```python
from esptest.devices.multimeter import Multimeter

mm = Multimeter(backend='gpib', address=22, sample_rate=0.001)
mm.device_start()
try:
    # Blocking capture; returns milliamperes
    samples = mm.measure_current(measure_time=1.0, max_value=0.1)
    print(samples)

    # Single-shot readings (instrument units, typically amperes / volts)
    amps = mm.measure_current_once()
    volts = mm.measure_voltage_once()
finally:
    mm.device_close()
```

You can also select first, then configure:

```python
mm = get_multimeter_specific(backend='gpib', address=22)
mm.log_path = './logs'
mm.sample_rate = 0.0001
mm.device_start()
data = mm.measure_current(0.2)
mm.device_close()
```

Notes:

- `sample_rate` is the period between samples in **seconds** (same convention
  as ATS). `sampling_frequency` is derived as `int(round(1 / sample_rate))`.
  It must be positive; `0` or a negative value raises `ValueError`.
- `device_start()` requires `sample_rate` first. `device_close()` is idempotent.
- `measure_current` returns a `list` of values in **mA**.
- `max_value` is the GPIB current range in amperes (default `0.1`).
- `measure_time` must cover at least one sample (`measure_time >= sample_rate`),
  otherwise `ValueError` is raised before any SCPI command is sent.
- `opc_timeout_s` defaults to `max(30, ceil(measure_time) + 10)` seconds so long
  captures are not aborted; pass it explicitly to override.
- Capture SCPI still follows ATS (`TRIG:SOUR IMM` → `INIT` → wait OPC → `*TRG`
  → `FETC?`); real-instrument semantics of that sequence are Draft / TBD.
- Linux `ask()` currently uses a large fixed read size (~80 MiB); short queries
  may shrink that buffer later.

## Low-level transport

Direct GPIB without the multimeter backend:

```python
from esptest.devices.multimeter.transport import open_gpib

transport = open_gpib(address=22)
print(transport.ask('*IDN?'))
transport.close()
```

Platform rules:

- **Windows** → pyvisa
- **Linux** + `resource=` → pyvisa
- **Linux** + `address=` (or auto-scan) → linux-gpib `Gpib`
