import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from esptest.testcase.result import (
    KNOWN_LOG_COLUMNS,
    KNOWN_PARAMS_COLUMNS,
    KNOWN_RESULT_COLUMNS,
    PerformanceResult,
    _datetime_to_iso,
    _validate_dict_values,
)

# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_known_columns_are_dicts_of_types() -> None:
    """KNOWN_* maps must contain type annotations for every entry."""
    assert isinstance(KNOWN_PARAMS_COLUMNS, dict) and KNOWN_PARAMS_COLUMNS
    assert isinstance(KNOWN_RESULT_COLUMNS, dict) and KNOWN_RESULT_COLUMNS
    for name, tp in KNOWN_PARAMS_COLUMNS.items():
        assert isinstance(name, str)
        assert tp is not None


def test_known_log_columns_defines_path_and_type() -> None:
    """Log entries must at least declare ``path`` and ``type`` as str."""
    assert KNOWN_LOG_COLUMNS == {'path': str, 'type': str}


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


def test_init_defaults() -> None:
    """Default construction yields empty state and no auto-save file."""
    perf = PerformanceResult()
    assert len(perf) == 0
    assert perf.records == []
    assert perf._save_path is None
    assert perf._auto_save is False
    assert perf._mandatory_params == []
    assert perf._mandatory_results == []


def test_init_mandatory_fields_stored() -> None:
    """Mandatory field lists are stored on the instance."""
    perf = PerformanceResult(
        mandatory_params=['target', 'type'],
        mandatory_results=['value'],
    )
    assert perf._mandatory_params == ['target', 'type']
    assert perf._mandatory_results == ['value']


def test_init_rejects_unknown_mandatory_params() -> None:
    """Unknown mandatory params name is rejected with a helpful message."""
    with pytest.raises(ValueError, match='Unknown mandatory params column'):
        PerformanceResult(mandatory_params=['not_a_real_col'])


def test_init_rejects_unknown_mandatory_results() -> None:
    """Unknown mandatory result name is rejected."""
    with pytest.raises(ValueError, match='Unknown mandatory result column'):
        PerformanceResult(mandatory_results=['not_a_real_col'])


def test_init_class_level_mandatory_used_as_default() -> None:
    """Subclass MANDATORY_* class attrs are used when not overridden."""

    class MyPerf(PerformanceResult):
        MANDATORY_PARAMS = ['target']
        MANDATORY_RESULTS = ['value']

    perf = MyPerf()
    assert perf._mandatory_params == ['target']
    assert perf._mandatory_results == ['value']


def test_init_auto_save_truncates_existing_file(tmp_path: Path) -> None:
    """auto_save=True must clear any pre-existing file on init."""
    path = tmp_path / 'out.json'
    path.write_text('stale data\n', encoding='utf-8')
    PerformanceResult(save_path=path, auto_save=True)
    assert path.read_text(encoding='utf-8') == ''


# ---------------------------------------------------------------------------
# add_record: happy path
# ---------------------------------------------------------------------------


def test_add_record_minimal() -> None:
    """Minimal add_record accepts empty params/result when no mandatory set."""
    perf = PerformanceResult()
    rec = perf.add_record()
    assert rec == {'params': {}, 'result': {}}
    assert len(perf) == 1


def test_add_record_full_record() -> None:
    """All optional DB columns are populated correctly in the record."""
    perf = PerformanceResult()
    started = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
    rec = perf.add_record(
        params={'target': 'esp32', 'type': 'tcp_tx', 'att': 30, 'rssi': -65},
        result={'value': 100.5, 'suffix': 'Mbps', 'value_list': [100.0, 101.1]},
        duration=60,
        logs=[
            {'path': '/logs/stdout.log', 'type': 'log'},
            {'path': '/logs/wifi.pcap', 'type': 'pcap'},
        ],
        brief_message='ok',
        started_at=started,
    )
    assert rec['params']['target'] == 'esp32'
    assert rec['result']['value'] == 100.5
    assert rec['duration'] == 60
    assert rec['logs'] == [
        {'path': '/logs/stdout.log', 'type': 'log'},
        {'path': '/logs/wifi.pcap', 'type': 'pcap'},
    ]
    assert rec['brief_message'] == 'ok'
    assert rec['started_at'] == '2026-04-20T12:00:00Z'


def test_add_record_accepts_iso_string_started_at() -> None:
    """started_at can be passed as an already-formatted ISO string."""
    perf = PerformanceResult()
    rec = perf.add_record(started_at='2026-04-20T00:00:00Z')
    assert rec['started_at'] == '2026-04-20T00:00:00Z'


def test_add_record_naive_datetime_treated_as_utc() -> None:
    """Naive datetimes are assumed to be UTC when serialized."""
    perf = PerformanceResult()
    rec = perf.add_record(started_at=datetime(2026, 4, 20, 12, 0, 0))
    assert rec['started_at'] == '2026-04-20T12:00:00Z'


def test_add_record_unknown_keys_pass_through() -> None:
    """Unknown params/result subfields are stored as-is (JSONB tolerant)."""
    perf = PerformanceResult()
    rec = perf.add_record(
        params={'target': 'esp32', 'raw': {'custom_param': 'x'}},
        result={'value': 1.0, 'raw': {'custom_metric': 42}},
    )
    assert rec['params']['raw']['custom_param'] == 'x'
    assert rec['result']['raw']['custom_metric'] == 42
    # do not allow unknown keys in params & result
    with pytest.raises(ValueError, match='custom_param'):
        perf.add_record(
            params={'target': 'esp32', 'custom_param': 'x'},
        )
    with pytest.raises(ValueError, match='custom_metric'):
        perf.add_record(
            result={'value': 1.0, 'custom_metric': 42},
        )


def test_add_record_omits_none_optional_columns() -> None:
    """Optional DB columns left as None are omitted from the record."""
    perf = PerformanceResult()
    rec = perf.add_record(params={'target': 'esp32'}, result={'value': 1.0})
    assert 'duration' not in rec
    assert 'logs' not in rec
    assert 'brief_message' not in rec
    assert 'started_at' not in rec


def test_add_record_int_accepted_for_float_field() -> None:
    """Known float columns accept plain int values."""
    perf = PerformanceResult()
    rec = perf.add_record(result={'value': 100})
    assert rec['result']['value'] == 100


def test_records_property_returns_list_copy() -> None:
    """records returns a shallow copy of the internal list and record dicts."""
    perf = PerformanceResult()
    perf.add_record(params={'target': 'esp32'}, result={'value': 1.0})
    snapshot = perf.records
    snapshot.append({'params': {}, 'result': {}})
    snapshot[0]['extra'] = 'added'
    assert len(perf._records) == 1
    assert 'extra' not in perf._records[0]


# ---------------------------------------------------------------------------
# add_record: mandatory field checks
# ---------------------------------------------------------------------------


def test_add_record_missing_mandatory_param_raises() -> None:
    """Mandatory params keys must be present."""
    perf = PerformanceResult(mandatory_params=['target'])
    with pytest.raises(ValueError, match='Missing mandatory field: target'):
        perf.add_record(params={}, result={'value': 1.0})


def test_add_record_missing_mandatory_result_raises() -> None:
    """Mandatory result keys must be present."""
    perf = PerformanceResult(mandatory_results=['value'])
    with pytest.raises(ValueError, match='Missing mandatory field: value'):
        perf.add_record(params={'target': 'esp32'}, result={})


def test_add_record_mandatory_none_value_treated_as_missing() -> None:
    """A mandatory key set to None is treated as missing."""
    perf = PerformanceResult(mandatory_params=['target'])
    with pytest.raises(TypeError, match='target must be str'):
        perf.add_record(params={'target': None}, result={})


# ---------------------------------------------------------------------------
# add_record: type checks
# ---------------------------------------------------------------------------


def test_add_record_invalid_param_values() -> None:
    # Known str field rejects non-str.
    perf = PerformanceResult()
    with pytest.raises(TypeError, match='target must be str'):
        perf.add_record(params={'target': 123}, result={})
    # Known float field rejects a str value.
    perf = PerformanceResult()
    with pytest.raises(TypeError, match='value must be float'):
        perf.add_record(params={}, result={'value': 'not a number'})
    # bool must not be silently accepted as int.
    perf = PerformanceResult()
    with pytest.raises(TypeError, match='att must be int'):
        perf.add_record(params={'att': True}, result={})
    # Known value field rejects non-bool.
    perf = PerformanceResult()
    with pytest.raises(TypeError, match='value must be float'):
        perf.add_record(params={}, result={'value': True})
    # List[float] rejects string elements.
    perf = PerformanceResult()
    with pytest.raises(TypeError, match='value_list must be list'):
        perf.add_record(params={}, result={'value_list': [1.0, 'oops']})
    # A List-typed column rejects non-list values.
    perf = PerformanceResult()
    with pytest.raises(TypeError, match='value_list must be list'):
        perf.add_record(params={}, result={'value_list': 'not a list'})
    # Known Dict[str, Any] field rejects non-dict.
    perf = PerformanceResult()
    with pytest.raises(TypeError, match='raw must be dict'):
        perf.add_record(params={'raw': 'not-a-dict'}, result={})


def test_add_record_type_checks() -> None:
    # duration must be int.
    perf = PerformanceResult()
    with pytest.raises(AssertionError, match='duration must be int'):
        perf.add_record(duration='60')  # type: ignore[arg-type]
    # brief_message must be str.
    perf = PerformanceResult()
    with pytest.raises(AssertionError, match='brief_message must be str'):
        perf.add_record(brief_message=123)  # type: ignore[arg-type]
    # logs must be a list.
    perf = PerformanceResult()
    with pytest.raises(AssertionError, match='logs must be a list'):
        perf.add_record(logs='not a list')  # type: ignore[arg-type]


def test_add_record_logs_entry_must_be_dict() -> None:
    """Every log entry must be a dict."""
    perf = PerformanceResult()
    with pytest.raises(TypeError, match='must be a dict'):
        perf.add_record(logs=[{'path': '/a.log', 'type': 'log'}, 'bad'])  # type: ignore[list-item]


def test_add_record_logs_requires_path() -> None:
    """Log entries missing ``path`` are rejected."""
    perf = PerformanceResult()
    with pytest.raises(ValueError, match="Missing mandatory field 'path' or 'type'"):
        perf.add_record(logs=[{'type': 'log'}])


def test_add_record_logs_requires_type() -> None:
    """Log entries missing ``type`` are rejected."""
    perf = PerformanceResult()
    with pytest.raises(ValueError, match="Missing mandatory field 'path' or 'type'"):
        perf.add_record(logs=[{'path': '/a.log'}])


def test_add_record_logs_path_must_be_str() -> None:
    """``path`` on a log entry must be str."""
    perf = PerformanceResult()
    with pytest.raises(TypeError, match=r'path must be str'):
        perf.add_record(logs=[{'path': 123, 'type': 'log'}])


def test_add_record_logs_type_field_must_be_str() -> None:
    """``type`` on a log entry must be str."""
    perf = PerformanceResult()
    with pytest.raises(TypeError, match=r'type must be str'):
        perf.add_record(logs=[{'path': '/a.log', 'type': 42}])


def test_add_record_logs_rejects_extra_keys() -> None:
    """Log entries only allow ``path`` and ``type`` keys."""
    perf = PerformanceResult()
    with pytest.raises(ValueError, match=r'Unknown field'):
        perf.add_record(logs=[{'path': '/a.log', 'type': 'log', 'size': 1234}])


def test_add_record_logs_accepts_only_path_and_type() -> None:
    """Logs with exactly the known keys are stored verbatim."""
    perf = PerformanceResult()
    rec = perf.add_record(
        logs=[
            {'path': '/logs/stdout.log', 'type': 'log'},
            {'path': '/logs/wifi.pcap', 'type': 'pcap'},
        ],
    )
    assert rec['logs'] == [
        {'path': '/logs/stdout.log', 'type': 'log'},
        {'path': '/logs/wifi.pcap', 'type': 'pcap'},
    ]


def test_add_record_started_at_wrong_type_raises() -> None:
    """started_at accepts only datetime or str."""
    perf = PerformanceResult()
    with pytest.raises(TypeError, match='started_at must be datetime or ISO string'):
        perf.add_record(started_at=12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# save / JSON output
# ---------------------------------------------------------------------------


def test_save_json_array(tmp_path: Path) -> None:
    """save() without jsonl writes a JSON array file."""
    path = tmp_path / 'out.json'
    perf = PerformanceResult()
    perf.add_record(params={'target': 'esp32'}, result={'value': 1.0})
    perf.add_record(params={'target': 'esp32c3'}, result={'value': 2.0})
    perf.save(path)

    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    assert isinstance(data, list) and len(data) == 2
    assert data[0]['params']['target'] == 'esp32'
    assert data[1]['result']['value'] == 2.0


def test_save_jsonl(tmp_path: Path) -> None:
    """save(jsonl=True) writes one JSON object per line."""
    path = tmp_path / 'out.jsonl'
    perf = PerformanceResult()
    perf.add_record(params={'target': 'esp32'}, result={'value': 1.0})
    perf.add_record(params={'target': 'esp32c3'}, result={'value': 2.0})
    perf.save(path, jsonl=True)

    lines = path.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])['params']['target'] == 'esp32'
    assert json.loads(lines[1])['result']['value'] == 2.0


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    """save() creates missing parent directories."""
    path = tmp_path / 'sub' / 'dir' / 'out.json'
    assert not path.parent.exists()
    perf = PerformanceResult()
    perf.add_record(params={'target': 'esp32'}, result={'value': 1.0})
    perf.save(path)
    assert path.exists()


def test_save_empty_writes_empty_array(tmp_path: Path) -> None:
    """save() with no records produces an empty JSON array."""
    path = tmp_path / 'empty.json'
    perf = PerformanceResult()
    perf.save(path)
    with open(path, encoding='utf-8') as f:
        assert json.load(f) == []


def test_save_uses_default_save_path(tmp_path: Path) -> None:
    """save() without args falls back to save_path from __init__."""
    path = tmp_path / 'default.json'
    perf = PerformanceResult(save_path=path)
    perf.add_record(params={'target': 'esp32'}, result={'value': 1.0})
    returned = perf.save()
    assert returned == path
    assert path.exists()


def test_save_without_any_path_raises() -> None:
    """save() raises when neither arg nor save_path is available."""
    perf = PerformanceResult()
    with pytest.raises(ValueError, match='save_path'):
        perf.save()


def test_save_overwrites_existing_file(tmp_path: Path) -> None:
    """save() fully overwrites existing content."""
    path = tmp_path / 'out.json'
    p1 = PerformanceResult()
    p1.add_record(params={'target': 'a'}, result={'value': 1.0})
    p1.save(path)
    p2 = PerformanceResult()
    p2.add_record(params={'target': 'b'}, result={'value': 2.0})
    p2.save(path)
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    assert len(data) == 1 and data[0]['params']['target'] == 'b'


# ---------------------------------------------------------------------------
# auto_save
# ---------------------------------------------------------------------------


def test_auto_save_appends_jsonl(tmp_path: Path) -> None:
    """auto_save appends one JSONL line per add_record call."""
    path = tmp_path / 'auto.jsonl'
    perf = PerformanceResult(save_path=path, auto_save=True)
    perf.add_record(params={'target': 'esp32'}, result={'value': 1.0})
    perf.add_record(params={'target': 'esp32c3'}, result={'value': 2.0})

    lines = path.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])['params']['target'] == 'esp32'
    assert json.loads(lines[1])['params']['target'] == 'esp32c3'


def test_auto_save_without_save_path_no_file(tmp_path: Path) -> None:
    """auto_save=True but no save_path does not create any file."""
    perf = PerformanceResult(auto_save=True)
    perf.add_record(params={'target': 'esp32'}, result={'value': 1.0})
    assert not list(tmp_path.iterdir())


def test_append_one_no_op_when_no_save_path() -> None:
    """_append_one is a no-op when _save_path is None (defensive branch)."""
    perf = PerformanceResult()
    perf._save_path = None
    perf._append_one({'params': {}, 'result': {}})
    assert perf.records == []


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_datetime_to_iso_helper() -> None:
    """_datetime_to_iso handles aware and naive datetimes."""
    aware = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
    assert _datetime_to_iso(aware) == '2026-04-20T12:00:00Z'
    naive = datetime(2026, 4, 20, 12, 0, 0)
    assert _datetime_to_iso(naive) == '2026-04-20T12:00:00Z'


def test_validate_dict_values() -> None:
    """_validate_dict_values accepts dict, list, int, float, bool, str."""
    _validate_dict_values({'x': 123, 'y': [1, 2, 3], 'z': {'a': 1, 'b': 2}})
    _validate_dict_values({'x': 'hi', 'y': [1, 2, 3], 'z': {'a': 'hello', 'b': 3.14}})
    _validate_dict_values({'x': 123, 'y': ['a', 'b', 'c'], 'z': {'a': 1, 'b': 2}})
    with pytest.raises(TypeError, match='Value of x'):
        _validate_dict_values({'x': None, 'y': [1, 2, 3], 'z': {'a': 1, 'b': 2}})
    with pytest.raises(TypeError, match='Value of y'):
        _validate_dict_values({'x': 'a', 'y': {1, 2}})


if __name__ == '__main__':
    # Breakpoints do not work with coverage, disable coverage for debugging
    pytest.main([__file__, '--no-cov', '--log-cli-level=DEBUG'])
