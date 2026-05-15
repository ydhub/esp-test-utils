## v0.4.0 (2026-05-14)


- feat: add fetch repo script
- feat: add script to control relay power on
- feat: add nvs dump args and reuse partition lookup
- fix: remove database / sqlalchemy from esptest
- feat: support download partition
- feat: add check serial port in use
- feat: add copy_bin cli options and option behavior tests
- fix: correct copy_bin zip output and add regression test

## v0.3.4 (2026-04-27)


- fix: make serial read error reconnect configurable
- fix: resolve data monitor review findings
- feat: support add data monitor and callback to port
- fix(port): propagate monitors and callbacks consistently
- fix: pexpect buffer maxread limit and data cache overflow

## v0.3.3 (2026-04-21)


- feat: parser support expand list
- feat: add index parser function
- feat: add performance result
- feat: shell_port support check is_alive
- fix: unzip bin path tmp dir

## v0.3.2 (2026-03-19)


- feat: add downbin with configs
- feat: add secure boot match check
- fix: parse partition for read-only dir
- change: add debug logs for downbin

## v0.3.1 (2026-01-16)


- feat: add diff values for pyecharts
- feat: add secure boot check
- fix: pass pytest on windows

## v0.3.0 (2025-12-10)


- feat: esp-listports support monitor mode
- feat: add more logs to H3CSwitch
- feat: esp-downbin support argument --force-no-stub
- feat: add h3c switch device control
- feat: add decorator timeit

## v0.2.3 (2025-11-14)


- feat: add shell port support
- fix: Fix esptool connect to given port
- fix: log of env config search dirs

## v0.2.2 (2025-10-29)


- feat: get test variables from shell env
- fix: flash esp32 option no-stub

## v0.2.1 (2025-09-24)


- feat(utility): support to flash bin to encrypted device
- feat: add runners database
- feat: add default gen part tool
- feat(utility): support to check flash enc from bin path
- fix: get baud from bin path sdkconfig file

## v0.2.0 (2025-07-16)


- feat: add wifi nic methods
- change: use interface for port and dut
- feat: support download bin
- fix: fix dependencies packaging
- feat: add check pip requirements

## v0.1.1 (2025-03-18)


- change: rename package name PEP-8

## v0.1.0 (2025-03-03)


- feat: add iperf test utility
- feat(init): add basic serial dut
- feat(init): basic template python package
- add README
