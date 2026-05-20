"""Ellisys Bluetooth Explorer (BEX400) air capture controller.

Uses ``esptest.sniffer.SnifferClient`` (btacli wrapper shipped with esp-test-utils).

Typical usage::

    from esptest.devices.bt_sniffer import EllisysSniffer

    with EllisysSniffer(host='localhost', port=12345) as sniffer:
        sniffer.start_recording()
        ...
        sniffer.stop_recording('/tmp/case_001.btt')
"""

import json
import os
import re
import time
from typing import Any, Optional

from ..logger import get_logger

logger = get_logger('devices.bt_sniffer')

_ANALYZER_ID_IN_UNIT_RE = re.compile(r'\(([A-Z0-9]+-\d+)')


class EllisysSnifferError(RuntimeError):
    """Raised for Ellisys btacli protocol / state errors."""


def btt_capture_filename(case_id: str, tag: str = '', ts: Optional[float] = None) -> str:
    """Build a ``.btt`` filename (Ellisys trace format only).

    Example: ``ESP32_BTPROF_SPP_50115_BEX400_22820_20260520_143025.btt``
    """
    name = case_id.strip().replace('.', '_')
    name = re.sub(r'[^\w\-]+', '_', name).strip('_') or 'unknown_case'
    ts = ts if ts is not None else time.time()
    date_part = time.strftime('%Y%m%d', time.localtime(ts))
    time_part = time.strftime('%H%M%S', time.localtime(ts))
    if tag:
        tag = re.sub(r'[^\w\-]+', '_', tag.strip()).strip('_')
        return f'{name}_{tag}_{date_part}_{time_part}.btt'
    return f'{name}_{date_part}_{time_part}.btt'


def _analyzer_id_from_unit(unit: str) -> str:
    match = _ANALYZER_ID_IN_UNIT_RE.search(unit or '')
    return match.group(1) if match else ''


def parse_analyzer_id_from_list(analyzers: Any, configured_id: str = '') -> str:
    """Extract analyzer id (e.g. ``BEX400-22820``) from btacli ``list_analyzers`` output.

    The ``list_analyzers`` JSON looks like::

        {"items": [
            {"item": {"Selected": "True",
                      "Unit": "Ellisys Bluetooth Explorer 400 (BEX400-22820, USB2)"}}
        ]}

    :param analyzers: response from ``SnifferClient.list_analyzers()``; tolerant to
        ``str`` / ``list`` / ``dict`` shapes.
    :param configured_id: user override; if set, returned as-is.
    :return: analyzer id, or empty string when nothing usable was found.
    """
    if configured_id:
        return configured_id.strip()
    if isinstance(analyzers, str):
        text = analyzers.strip()
        if text.startswith('{'):
            try:
                analyzers = json.loads(text)
            except json.JSONDecodeError:
                return _analyzer_id_from_unit(text) or text
        else:
            return _analyzer_id_from_unit(text) or text
    if isinstance(analyzers, list):
        selected = ''
        fallback = ''
        for entry in analyzers:
            if isinstance(entry, str):
                aid = _analyzer_id_from_unit(entry) or entry
            elif isinstance(entry, dict):
                item = entry.get('item', entry)
                if not isinstance(item, dict):
                    continue
                unit = str(item.get('Unit', ''))
                aid = _analyzer_id_from_unit(unit)
                if str(item.get('Selected', '')).lower() == 'true' and aid:
                    selected = aid
                elif aid and not fallback:
                    fallback = aid
                continue
            else:
                aid = parse_analyzer_id_from_list(entry)
            if aid:
                return aid
        return selected or fallback
    if isinstance(analyzers, dict):
        if 'items' in analyzers:
            return parse_analyzer_id_from_list(analyzers['items'])
        unit = analyzers.get('Unit')
        if unit:
            return _analyzer_id_from_unit(str(unit))
    return ''


class EllisysSniffer:
    """Ellisys Bluetooth Explorer 400 sniffer controller (btacli Remote Control).

    The Ellisys "Bluetooth Analyzer btacli" GUI must be running on ``host`` with
    Remote Control enabled (default TCP port 12345). When ``analyzer_id`` is not
    given, the currently selected (or the first available) analyzer is used.
    """

    DEFAULT_HOST = 'localhost'
    DEFAULT_PORT = 12345
    BTT_SUFFIX = '.btt'

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        analyzer_id: str = '',
    ) -> None:
        self.host = str(host)
        self.port = int(port)
        self.analyzer_id = analyzer_id.strip() if analyzer_id else ''
        self._client: Any = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def connect(self) -> str:
        """Connect to btacli Remote Control and select an analyzer.

        :return: id of the selected analyzer (e.g. ``BEX400-22820``).
        :raises EllisysSnifferError: when no analyzer can be selected or btacli is missing.
        """
        from esptest.sniffer import SnifferClient

        self._client = SnifferClient(host=self.host, port=self.port)
        analyzers = self._client.list_analyzers()
        if not analyzers:
            raise EllisysSnifferError(
                f'No analyzer reported by Ellisys Remote Control at {self.host}:{self.port}'
            )
        analyzer_id = parse_analyzer_id_from_list(analyzers, self.analyzer_id)
        if not analyzer_id:
            raise EllisysSnifferError(f'Cannot determine analyzer id from: {analyzers!r}')
        self._client.select_analyzer(analyzer_id)
        self.analyzer_id = analyzer_id
        logger.info(f'EllisysSniffer: selected analyzer {analyzer_id} ({self.host}:{self.port})')
        return analyzer_id

    def start_recording(self) -> None:
        """Start a new recording on the selected analyzer."""
        if self._client is None:
            raise EllisysSnifferError('EllisysSniffer is not connected; call connect() first.')
        if self._recording:
            logger.warning('EllisysSniffer: already recording; ignoring start_recording()')
            return
        self._client.start_recording()
        self._recording = True
        logger.info('EllisysSniffer: recording started')

    def stop_recording(self, output_path: Optional[str]) -> str:
        """Stop the current recording and save the ``.btt`` to ``output_path``.

        :param output_path: file path where the ``.btt`` should be written.
            ``.btt`` suffix is appended automatically when missing. Parent
            directory is created when it does not exist.
        :return: actual output path, or empty string when not currently recording.
        """
        if not self._recording or self._client is None:
            return ''
        out = ''
        if output_path:
            out = output_path if output_path.endswith(self.BTT_SUFFIX) else output_path + self.BTT_SUFFIX
            parent = os.path.dirname(out)
            if parent:
                os.makedirs(parent, exist_ok=True)
        try:
            if out:
                self._client.stop_recording(out)
                logger.info(f'EllisysSniffer: saved capture to {out}')
            else:
                self._client.abort_recording()
            return out
        finally:
            self._recording = False

    def close(self) -> None:
        if self._recording and self._client is not None:
            try:
                self._client.abort_recording()
            except Exception as e:  # noqa: BLE001
                logger.warning(f'EllisysSniffer: close() failed to abort recording: {e}')
        self._recording = False
        self._client = None

    def __enter__(self) -> 'EllisysSniffer':
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
