try:
    # Run from `python -m esptest.scripts.list_ports`
    from ..devices.esp_serial import list_all_esp_ports
except ImportError:
    from esptest.devices.esp_serial import list_all_esp_ports


def main() -> None:
    print('All devices:')
    print('Device,        Location,    esptool,   target,   description')
    for port in list_all_esp_ports():
        desc = port.chip_description if port.support_esptool else port.serial_description
        print(f'{port.device:>10s},  {port.location:12s},  {port.support_esptool},   {port.target:8s},  {desc:30s}')


if __name__ == '__main__':
    main()
