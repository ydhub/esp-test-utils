import os
from typing import FrozenSet, Optional, Tuple

# Default: Espressif USB-SPI-BRIDGE — not a UART ROM bootloader port.
# '303a:4001' is the VID:PID of the Espressif USB-SPI-BRIDGE.
_DEFAULT_SKIP_ESPTOOL_DETECT_VID_PID = '303a:4001'
_DISABLE_SKIP_TOKENS = frozenset(['', 'none', 'off'])


def parse_skip_esptool_detect_vid_pid(raw: Optional[str]) -> FrozenSet[Tuple[int, int]]:
    """Parse ``vid:pid`` skip list for esptool detect.

    Args:
        raw: Env value or ``None`` when unset.
            - ``None`` → built-in default (``303a:4001``)
            - empty / ``none`` / ``off`` (case-insensitive) → empty set (do not skip)
            - otherwise → comma-separated ``vid:pid`` hex pairs (optional ``0x``)

    Returns:
        frozenset of ``(vid, pid)`` integers.
    """
    if raw is None:
        raw = _DEFAULT_SKIP_ESPTOOL_DETECT_VID_PID
    text = raw.strip().lower()
    if text in _DISABLE_SKIP_TOKENS:
        return frozenset()

    pairs = []
    for item in text.split(','):
        item = item.strip()
        if not item:
            continue
        if ':' not in item:
            raise ValueError(f'Invalid ESPTEST_SKIP_ESPTOOL_DETECT_VID_PID entry {item!r}; expected vid:pid')
        vid_s, pid_s = item.split(':', 1)
        pairs.append((int(vid_s, 16), int(pid_s, 16)))
    return frozenset(pairs)


class DefaultConfig:
    # default port expect timeout
    PORT_EXPECT_TIMEOUT = int(os.environ.get('ESPTEST_PORT_EXPECT_TIMEOUT', 30))

    # older data cache will be discarded if it is larger than 2x limit
    DATA_CACHE_SIZE_LIMIT = int(os.environ.get('ESPTEST_DATA_CACHE_SIZE_LIMIT', 1 * 1024 * 1024))

    # port spawn maxread size, max buffer read for expect process, default 10K
    PORT_SPAWN_MAXREAD = int(os.environ.get('ESPTEST_PORT_SPAWN_MAXREAD', 10 * 1024))

    # allow serial read-thread error reconnect attempts
    ALLOW_SERIAL_ERROR_RECONNECT_COUNT = int(os.environ.get('ESPTEST_ALLOW_SERIAL_ERROR_RECONNECT_COUNT', 0))

    # VID:PID pairs skipped by esptool detect_chip during port listing.
    # Env ESPTEST_SKIP_ESPTOOL_DETECT_VID_PID: unset=default, none/off/''=disable, else replace list.
    SKIP_ESPTOOL_DETECT_VID_PID = parse_skip_esptool_detect_vid_pid(
        os.environ['ESPTEST_SKIP_ESPTOOL_DETECT_VID_PID']
        if 'ESPTEST_SKIP_ESPTOOL_DETECT_VID_PID' in os.environ
        else None
    )


g = DefaultConfig()
