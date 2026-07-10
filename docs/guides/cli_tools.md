# Command line tools

Installing `esp-test-utils` also installs a set of `esp-*` console scripts for
lab automation. Run any of them with `-h`/`--help` for the full option list.

## Overview

| Command          | Description                                                        |
| ---------------- | ------------------------------------------------------------------ |
| `esp-listports`  | List connected serial ports (text or JSON).                        |
| `esp-monitor`    | Serial monitor (wraps `esp-idf-monitor`).                          |
| `esp-downbin`    | Flash firmware to one or many serial ports.                        |
| `esp-copybin`    | Copy/zip build artifacts (bin/elf/map) to a destination.           |
| `esp-setatt`     | Set an attenuator value.                                           |
| `esp-relay`      | Control a serial relay board.                                      |
| `esp-uhubctl`    | Control and inspect USB hubs via `uhubctl`/sysfs (Linux).          |
| `esp-tempbox`    | Control a U680 temperature box over Modbus.                        |
| `esp-fetch-repo` | Fetch/clone a git repository to a local path.                      |
| `esp-pipcheck`   | Check installed packages against a requirements file.              |

## `esp-listports`

```bash
esp-listports                 # human-readable list
esp-listports --format json   # machine-readable
esp-listports --monitor       # run the uart port monitor
```

## `esp-downbin`

Flash an ESP firmware build to serial ports.

```bash
esp-downbin ./build -p ttyUSB0 ttyUSB1     # specific ports
esp-downbin ./build --all                  # every detected serial port
esp-downbin ./build --range 0-10           # ttyUSB0 .. ttyUSB10 (Linux)
esp-downbin ./build -b 921600 --no-erase-nvs
```

Useful options: `--baudrate/-b`, `--max-workers`, `--force-no-stub`,
`--verbose/-v`.

## `esp-copybin`

```bash
esp-copybin ./build ./artifacts            # copy bin/elf/map
esp-copybin ./build out.zip --zip          # zip the artifacts
esp-copybin ./build ./artifacts --no-elf   # skip elf/map files
```

## `esp-setatt`

```bash
esp-setatt -v 30 -p /dev/ttyUSB0           # set 30 dB attenuation
esp-setatt -v 30 -p 1-5.1 --type <att_type>
```

`-p/--port` accepts a device path or a USB location.

## `esp-relay`

```bash
esp-relay open  --port /dev/ttyUSB0
esp-relay close --port /dev/ttyUSB0
esp-relay check-phone --port /dev/ttyUSB0
```

Custom open/close command bytes can be supplied with `--open-cmd` /
`--close-cmd`.

## `esp-uhubctl` (Linux)

```bash
esp-uhubctl ls                             # list hubs/ports
esp-uhubctl ls -a                          # include empty ports
esp-uhubctl <action> --port 1-6.1.2        # location auto-split into hub+port
esp-uhubctl <action> --hub 1-6.1 --port 2  # explicit hub + bare port
```

Options include `--sudo`, `--timeout`, and `--interval` (for monitoring).

```{note}
`esp-uhubctl` depends on the Linux `uhubctl` tool and USB sysfs, so it is not
available on Windows/macOS.
```

## `esp-tempbox`

```bash
esp-tempbox --mode read                    # read current temperature
esp-tempbox --mode custom --temp 25.0      # set a custom target
esp-tempbox --mode program --program 1     # run a stored program
esp-tempbox --mode stop
```

Use `--port` to pick a serial device (auto-detected when omitted) and
`--address` for the Modbus slave address.

## `esp-fetch-repo`

```bash
esp-fetch-repo --url <git-url> --path ./repo --ref origin/master --depth 1
```

## `esp-pipcheck`

```bash
esp-pipcheck requirements.txt
```

Checks that the current environment satisfies the given requirements file.
