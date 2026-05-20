"""Unit tests for esptest.devices.bt_sniffer (no real Ellisys hardware needed)."""

import os
from unittest import mock

import pytest

from esptest.devices.bt_sniffer import (
    EllisysSniffer,
    EllisysSnifferError,
    btt_capture_filename,
    parse_analyzer_id_from_list,
)


def test_parse_analyzer_id_from_btacli_json() -> None:
    analyzers = {
        'items': [{
            'item': {
                'Selected': 'True',
                'Unit': 'Ellisys Bluetooth Explorer 400 (BEX400-22820, USB2)',
            },
        }],
    }
    assert parse_analyzer_id_from_list(analyzers) == 'BEX400-22820'


def test_parse_analyzer_id_from_list_picks_selected() -> None:
    analyzers = {
        'items': [
            {'item': {'Selected': 'False', 'Unit': 'Ellisys Bluetooth Explorer 400 (BEX400-11111, USB2)'}},
            {'item': {'Selected': 'True', 'Unit': 'Ellisys Bluetooth Explorer 400 (BEX400-22222, USB2)'}},
        ],
    }
    assert parse_analyzer_id_from_list(analyzers) == 'BEX400-22222'


def test_parse_analyzer_id_configured_override() -> None:
    analyzers = {'items': []}
    assert parse_analyzer_id_from_list(analyzers, 'BEX400-99999') == 'BEX400-99999'


def test_parse_analyzer_id_empty() -> None:
    assert parse_analyzer_id_from_list({'items': []}) == ''
    assert parse_analyzer_id_from_list(None) == ''
    assert parse_analyzer_id_from_list('') == ''


def test_btt_capture_filename() -> None:
    name = btt_capture_filename('ESP32.BTPROF_SPP_50115', 'BEX400-22820', ts=1746952225)
    assert name.endswith('.btt')
    assert 'ESP32_BTPROF_SPP_50115' in name
    assert 'BEX400-22820' in name


def test_parse_analyzer_id_from_unit_string() -> None:
    unit = 'Ellisys Bluetooth Explorer 400 (BEX400-22820, USB2)'
    assert parse_analyzer_id_from_list(unit) == 'BEX400-22820'


def _patch_sniffer_client(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    """Patch ``esptest.sniffer.SnifferClient`` for unit tests without hardware."""
    client_cls = mock.MagicMock()
    monkeypatch.setattr('esptest.sniffer.SnifferClient', client_cls)
    return client_cls


def test_connect_uses_first_analyzer(monkeypatch: pytest.MonkeyPatch) -> None:
    client_cls = _patch_sniffer_client(monkeypatch)
    client_cls.return_value.list_analyzers.return_value = {
        'items': [{'item': {'Selected': 'True', 'Unit': 'Ellisys Bluetooth Explorer 400 (BEX400-22820, USB2)'}}],
    }

    sniffer = EllisysSniffer(host='127.0.0.1', port=12345)
    analyzer_id = sniffer.connect()

    assert analyzer_id == 'BEX400-22820'
    assert sniffer.analyzer_id == 'BEX400-22820'
    client_cls.assert_called_once_with(host='127.0.0.1', port=12345)
    client_cls.return_value.select_analyzer.assert_called_once_with('BEX400-22820')


def test_connect_uses_configured_analyzer_id(monkeypatch: pytest.MonkeyPatch) -> None:
    client_cls = _patch_sniffer_client(monkeypatch)
    client_cls.return_value.list_analyzers.return_value = {
        'items': [{'item': {'Selected': 'True', 'Unit': 'Ellisys Bluetooth Explorer 400 (BEX400-22820, USB2)'}}],
    }

    sniffer = EllisysSniffer(analyzer_id='BEX400-99999')
    assert sniffer.connect() == 'BEX400-99999'
    client_cls.return_value.select_analyzer.assert_called_once_with('BEX400-99999')


def test_connect_no_analyzer_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client_cls = _patch_sniffer_client(monkeypatch)
    client_cls.return_value.list_analyzers.return_value = []

    with pytest.raises(EllisysSnifferError):
        EllisysSniffer().connect()


def test_start_requires_connect() -> None:
    with pytest.raises(EllisysSnifferError):
        EllisysSniffer().start_recording()


def test_stop_recording_writes_btt(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client_cls = _patch_sniffer_client(monkeypatch)
    client_cls.return_value.list_analyzers.return_value = {
        'items': [{'item': {'Selected': 'True', 'Unit': 'BEX400 (BEX400-22820, USB2)'}}],
    }

    sniffer = EllisysSniffer()
    sniffer.connect()
    sniffer.start_recording()
    assert sniffer.is_recording is True

    target = tmp_path / 'subdir' / 'case_001'  # no extension
    out = sniffer.stop_recording(str(target))

    assert out.endswith('.btt')
    assert os.path.isdir(target.parent)
    assert sniffer.is_recording is False
    client_cls.return_value.stop_recording.assert_called_once_with(str(out))


def test_stop_recording_when_not_recording_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    client_cls = _patch_sniffer_client(monkeypatch)
    client_cls.return_value.list_analyzers.return_value = {
        'items': [{'item': {'Selected': 'True', 'Unit': 'BEX400 (BEX400-22820, USB2)'}}],
    }

    sniffer = EllisysSniffer()
    sniffer.connect()
    assert sniffer.stop_recording('/tmp/whatever.btt') == ''
    client_cls.return_value.stop_recording.assert_not_called()
    client_cls.return_value.abort_recording.assert_not_called()


def test_context_manager_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    client_cls = _patch_sniffer_client(monkeypatch)
    client_cls.return_value.list_analyzers.return_value = {
        'items': [{'item': {'Selected': 'True', 'Unit': 'BEX400 (BEX400-22820, USB2)'}}],
    }

    with EllisysSniffer() as sniffer:
        assert sniffer.is_connected
        sniffer.start_recording()

    client_cls.return_value.abort_recording.assert_called_once()
    assert not sniffer.is_connected
