# Firmware package shapes

`ParseBinPath`, DUT `bin_path`, and `esp-downbin` accept several firmware
layouts. Detection order for a directory is:

1. **standard** — IDF flash package (`bootloader/` + `partition_table/`)
2. **raw** — directory with `raw_flash.json`
3. **merged** — exactly one valid esptool `merge-bin` image (``.bin``)

A bare ``.bin`` file is treated as **merged** when the API/CLI allows it
(`ParseBinPath`, or `esp-downbin --merged`). A bare ``.bin`` used with
`--raw` is wrapped into a temporary raw package (see below).

Standard packages never silently fall back to merged or raw.

## Standard (IDF build)

Typical `idf.py build` / CI artifact directory:

```text
./build/
  bootloader/
  partition_table/
  flasher_args.json
  ...
```

```python
from esptest.utility.parse_bin_path import ParseBinPath

parsed = ParseBinPath('./build')
args = parsed.flash_bin_args(erase_nvs=True)
```

```bash
esp-downbin ./build -p ttyUSB0
```

Zip archives and `http(s)` URLs that unpack to this layout work the same way
via `bin_path_to_dir` / `ParseBinPath`.

## Raw (`raw_flash.json`)

Use a raw package when you flash a single image at a fixed offset (special
firmware, bootloader-only, RF cal, …) without a full IDF flash layout.

### Package layout

```text
./my_raw_pkg/
  raw_flash.json
  firmware.bin
```

`raw_flash.json` fields:

| Field              | Required | Description                                      |
| ------------------ | -------- | ------------------------------------------------ |
| `offset`           | yes      | Flash offset, e.g. `"0x1000"`                    |
| `chip`             | yes      | Target chip, e.g. `"esp32"`, `"esp32c5"`         |
| `file`             | yes      | Bin filename relative to the package directory   |
| `write_flash_args` | no       | Extra `write_flash` args (defaults applied if omitted) |

Example marker:

```json
{
  "offset": "0x1000",
  "chip": "esp32",
  "file": "firmware.bin",
  "write_flash_args": [
    "--flash_mode", "dio",
    "--flash_freq", "40m",
    "--flash_size", "detect"
  ]
}
```

### Create a package in Python

```python
from pathlib import Path

from esptest.utility.raw_flash import write_raw_flash

pkg = Path('./my_raw_pkg')
pkg.mkdir(parents=True, exist_ok=True)
# copy or write your image as pkg / 'firmware.bin'
write_raw_flash(pkg, offset='0x1000', chip='esp32', file='firmware.bin')
```

Or materialize a temp package from a bare `.bin`:

```python
from esptest.utility.raw_flash import materialize_raw_dir

pkg_dir = materialize_raw_dir('./firmware.bin', offset='0x1000', chip='esp32')
```

### Use as `bin_path`

`ParseBinPath` and DUT flash pick up `raw_flash.json` automatically:

```python
from esptest.all import DutConfig, dut_wrapper
from esptest.utility.parse_bin_path import ParseBinPath

parsed = ParseBinPath('./my_raw_pkg')
# flash at offset from raw_flash.json; erase_nvs is skipped in raw mode
args = parsed.flash_bin_args(erase_nvs=True)

config = DutConfig(
    name='DUT',
    device='/dev/ttyUSB0',
    support_esptool=True,
    bin_path='./my_raw_pkg',
)
with dut_wrapper(config) as dut:
    dut.download_bin()
```

Constructor overrides (API only; not wired through `download_bin` cache):

```python
ParseBinPath('./my_raw_pkg', raw_offset='0x2000', raw_chip='esp32s3')
```

CLI examples:

```bash
# package directory (marker present)
esp-downbin ./my_raw_pkg --raw -p ttyUSB0

# override offset/chip without editing the package
esp-downbin ./my_raw_pkg --raw --offset 0x2000 --chip esp32s3 -p ttyUSB0

# bare .bin — requires --offset and --chip (builds a temp raw package)
esp-downbin ./firmware.bin --raw --offset 0x1000 --chip esp32 -p ttyUSB0
```

`--raw` and `--merged` are mutually exclusive. For `--raw`, NVS erase is
disabled (raw mode has no partition table to erase).

## Merged (esptool `merge-bin`)

A single image written at `0x0`, usually produced by `esptool merge_bin`.

```bash
esp-downbin ./merged.bin --merged -p ttyUSB0
# directory that is not standard/raw and contains exactly one merged .bin
esp-downbin ./artifacts --merged -p ttyUSB0
```

`--merged` enables merged resolution for bare `.bin` / non-package dirs; a
standard IDF layout or `raw_flash.json` package in that path still takes
precedence.

```python
parsed = ParseBinPath('./merged.bin')  # mode merged
parsed = ParseBinPath('./artifacts')   # dir containing one probed merged .bin
```

`ParseBinPath` probes bootloader / partition table / app magic inside the
image. Optional NVS erase uses the probed partition table when present; if no
`nvs` partition is found, erase is skipped with a warning.

## Choosing a shape

| Need                                         | Shape    |
| -------------------------------------------- | -------- |
| Normal IDF build / CI flash package          | standard |
| One file at a custom offset                  | raw      |
| Full-chip image from `merge-bin`             | merged   |

See also {doc}`cli_tools` (`esp-downbin`) and {doc}`dut` (`DutConfig.bin_path`).
