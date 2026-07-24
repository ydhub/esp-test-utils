from pathlib import Path

import esptest.common.compat_typing as t

from ...devices.serial_tools import compute_serial_port


def _download_device_from_config(dut_config: t.Any) -> str:
    """Flash/download serial device (falls back to log ``device``)."""
    return str(dut_config.download_device or dut_config.device or '')


def _ports_equal(port_a: str, port_b: str) -> bool:
    """True when two port specs resolve to the same serial device."""
    if not port_a or not port_b:
        return port_a == port_b
    if port_a == port_b:
        return True
    return compute_serial_port(port_a) == compute_serial_port(port_b)


def should_save_download_log(dut_config: t.Any) -> bool:
    """Whether a dual-UART setup should save download-side logs."""
    if not getattr(dut_config, 'save_download_log', True):
        return False
    download = _download_device_from_config(dut_config)
    log_dev = str(dut_config.device or '')
    if not download or not log_dev:
        return False
    return not _ports_equal(download, log_dev)


def default_download_log_file(dut_config: t.Any) -> str:
    """Resolve download log path (config value or ``<stem>_download``)."""
    if dut_config.download_log_file:
        return str(dut_config.download_log_file)
    if not should_save_download_log(dut_config) or not dut_config.log_file:
        return ''
    log_path = Path(dut_config.log_file)
    name = dut_config.name or ''
    if name and name in log_path.name:
        return str(log_path.with_name(log_path.name.replace(name, f'{name}_download')))
    return str(log_path.with_name(f'{log_path.stem}_download{log_path.suffix}'))
