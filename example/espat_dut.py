# from esptest.config import EnvConfig
import logging
import time

from esptest.all import DutConfig, dut_wrapper
from esptest.all import EspDut as Dut
from esptest.common.timestamp import timestamp_slug


class ESPATDut(Dut):
    # customer methods
    def at_rst(self) -> None:
        self.write_line('AT+RST')
        self.expect('ready')


def espat_dut_reset() -> None:
    """Log UART and download UART are different serial ports.

    ``device`` is the console/log port; ``download_device`` is used for
    ``get_chip_info`` / ``hard_reset`` / ``download_bin``. ``dut.esp`` stays
    ``None`` because the log port does not host the esptool handle.

    Dual-UART also monitors ``download_device`` into
    ``<log_stem>_download.log`` (disable with ``save_download_log=False``).
    """
    _config = DutConfig(
        name='AT1',
        device='/dev/ttyUSB1',  # log UART
        download_device='/dev/ttyUSB0',  # flash / reset UART
        support_esptool=True,
        baudrate=115200,
        bin_path='./ESP32C5-AT.zip',
        log_path=f'./dut_logs/{timestamp_slug()}',
        # download_serial_configs={'timeout': 0.01},
        # save_download_log=False,
    )

    with dut_wrapper(_config, wrap_cls=ESPATDut) as dut:
        logging.info('AT1 log port: %s', dut.log_port)
        logging.info('AT1 download port: %s', dut.download_port)
        logging.info('AT1 bin_path: %s', dut.bin_path)
        assert dut.esp is None  # log port is plain serial
        info = dut.get_chip_info()
        logging.info(f'chip={info.chip_name} rev_full={info.chip_rev_full} mac={info.mac}')
        dut.download_bin()
        time.sleep(5)
        dut.hard_reset()
        time.sleep(5)
        dut.at_rst()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    espat_dut_reset()
