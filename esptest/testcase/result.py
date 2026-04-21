"""
Performance test result recording and JSON export.

Each accumulated record corresponds to one ``TestResultDetail`` database row
and can be dumped as JSON / JSONL for batch import into the database.

Database schema (TestResultDetail) that records target:

    params:        dict[str, Any]           (JSONB, required)
    result:        dict[str, Any]           (JSONB, required)
    duration:      int | None
    logs:          list[dict[str, Any]] | None
    brief_message: str | None
    started_at:    datetime | None

The ``params`` / ``result`` dicts are free-form JSONB, but a set of well known
subfields is defined below. Values under those keys are type-checked when
calling :meth:`PerformanceResult.add_record`. Unknown keys are accepted as-is
so test authors can still add ad-hoc data.

``logs`` is a list describing collected log files, e.g.::

    [
        {"path": "/logs/stdout.log", "type": "log"},
        {"path": "/logs/wifi.pcap",  "type": "pcap"},
    ]

Each entry must contain exactly the keys defined in :data:`KNOWN_LOG_COLUMNS`
(``path`` and ``type``); any extra key is rejected.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import esptest.common.compat_typing as t

from ..logger import get_logger

logger = get_logger('testcase.result')


# Known params columns (all optional by default). Type is used for validation.
# Each value is either a plain type (``str`` / ``int`` / ``float`` / ``bool`` /
# ``list`` / ``dict``) or a tuple ``(list, elem_type)`` to also check the
# element type of a list.
KNOWN_PARAMS_COLUMNS: t.Dict[str, Any] = {
    'version': str,
    'description': str,
    'case_name': str,
    'target': str,
    'type': str,
    'ap_name': str,
    'config': str,
    'att': int,
    'rssi': int,
    'channel': int,
    'raw': dict,
}

# Known result columns (all optional by default). Type is used for validation.
KNOWN_RESULT_COLUMNS: t.Dict[str, Any] = {
    'prefix': str,
    'value': float,
    'value_list': list,
    'suffix': str,
    'min_heap': int,
    'success_rate': float,
    'raw': dict,
}

# Required subfields for every entry in the ``logs`` list. Describes a single
# collected log artifact (file path + its kind, e.g. ``log`` / ``pcap``).
KNOWN_LOG_COLUMNS: t.Dict[str, Any] = {
    'path': str,
    'type': str,
}


def _type_name(tp: t.Type) -> str:
    return getattr(tp, '__name__', None) or str(tp)


def _validate_dict_values(data: t.Dict[str, Any]) -> None:
    """values must be str/int/float/bool/None"""
    for key, value in data.items():
        assert isinstance(key, str)
        # if value is None:
        #     # allow None
        #     continue
        if isinstance(value, dict):
            _validate_dict_values(value)
        elif isinstance(value, list):
            assert all(isinstance(item, (int, float, bool, str)) for item in value)
        elif isinstance(value, (int, float, bool, str)):
            pass
        else:
            raise TypeError(f'Value of {key} must be str/int/float/bool, got {type(value).__name__}')


def _validate_params(
    data: t.Dict[str, Any],
    mandatory_params: t.List[str],
) -> None:
    """Check data is a valid params dict"""
    for key in mandatory_params:
        if key not in data:
            raise ValueError(f'Missing mandatory field: {key}')
    for key, value in data.items():
        if key not in KNOWN_PARAMS_COLUMNS:
            raise ValueError(f"Unknown field '{key}'")
        allowed_types = [KNOWN_PARAMS_COLUMNS[key]]
        if KNOWN_PARAMS_COLUMNS[key] is float:
            allowed_types.append(int)
        if type(value) not in allowed_types:
            raise TypeError(
                f'Value of {key} must be {_type_name(KNOWN_PARAMS_COLUMNS[key])}, got {type(value).__name__}'
            )
        if isinstance(value, dict):
            _validate_dict_values(value)
        elif isinstance(value, list):
            if not all(isinstance(item, (int, float, bool, str)) for item in value):
                raise TypeError(f'Value of {key} must be list of str/int/float/bool, got {type(value).__name__}')


def _validate_result(
    data: t.Dict[str, Any],
    mandatory_results: t.List[str],
) -> None:
    """Check data is a valid result dict"""
    for key in mandatory_results:
        if key not in data:
            raise ValueError(f'Missing mandatory field: {key}')
    for key, value in data.items():
        if key not in KNOWN_RESULT_COLUMNS:
            raise ValueError(f"Unknown field '{key}'")
        allowed_types = [KNOWN_RESULT_COLUMNS[key]]
        if KNOWN_RESULT_COLUMNS[key] is float:
            allowed_types.append(int)
        if type(value) not in allowed_types:
            raise TypeError(
                f'Value of {key} must be {_type_name(KNOWN_RESULT_COLUMNS[key])}, got {type(value).__name__}'
            )
        if key == 'value_list':
            if not all(isinstance(item, (int, float)) for item in value):
                raise TypeError(f'Value of {key} must be list of float, got {map(type, value)}')
        if isinstance(value, dict):
            _validate_dict_values(value)
        elif isinstance(value, list):
            if not all(isinstance(item, (int, float, bool, str)) for item in value):
                raise TypeError(f'Value of {key} must be list of str/int/float/bool, got {map(type, value)}')


def _validate_logs(
    data: t.List[t.Dict[str, Any]],
) -> None:
    """Check data is a valid logs list"""
    for entry in data:
        if not isinstance(entry, dict):
            raise TypeError('Logs entry must be a dict')
        if 'path' not in entry or 'type' not in entry:
            raise ValueError("Missing mandatory field 'path' or 'type'")
        for key, value in entry.items():
            if key not in KNOWN_LOG_COLUMNS:
                raise ValueError(f"Unknown field '{key}'")
            if not isinstance(value, KNOWN_LOG_COLUMNS[key]):
                raise TypeError(f'Value of {key} must be {_type_name(KNOWN_LOG_COLUMNS[key])}, got {type(value)}')


def _datetime_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace('+00:00', 'Z')


class PerformanceResult:
    """Accumulate performance test records and export them to JSON.

    Each record added via :meth:`add_record` corresponds to exactly one
    ``TestResultDetail`` row in the database.

    Typical usage::

        perf = PerformanceResult(
            save_path='performance_result.json',
            auto_save=True,
            mandatory_params=['target', 'type'],
            mandatory_results=['value'],
        )
        perf.add_record(
            params={'target': 'esp32', 'type': 'tcp_tx', 'att': 30},
            result={'value': 100.5, 'suffix': 'Mbps'},
            duration=60,
        )
        perf.save('performance_result.json')
    """

    # Subclasses may override these to enforce mandatory fields by default.
    MANDATORY_PARAMS: t.List[str] = []
    MANDATORY_RESULTS: t.List[str] = []

    def __init__(
        self,
        save_path: t.Optional[t.Union[str, Path]] = None,
        auto_save: bool = False,
        mandatory_params: t.Optional[t.List[str]] = None,
        mandatory_results: t.Optional[t.List[str]] = None,
    ) -> None:
        """
        Args:
            save_path: File used by ``auto_save`` and as the default for
                :meth:`save`. When ``auto_save`` is enabled this file is
                appended one JSON object per line (JSONL).
            auto_save: If True, each :meth:`add_record` call appends a line to
                ``save_path``.
            mandatory_params: Keys that must be present in ``params`` on every
                call to :meth:`add_record`. Defaults to ``MANDATORY_PARAMS``.
                All names must be in :data:`KNOWN_PARAMS_COLUMNS`.
            mandatory_results: Keys that must be present in ``result`` on every
                call to :meth:`add_record`. Defaults to ``MANDATORY_RESULTS``.
                All names must be in :data:`KNOWN_RESULT_COLUMNS`.
        """
        self._save_path = Path(save_path) if save_path else None
        self._auto_save = bool(auto_save)
        self._mandatory_params = list(mandatory_params if mandatory_params is not None else self.MANDATORY_PARAMS)
        self._mandatory_results = list(mandatory_results if mandatory_results is not None else self.MANDATORY_RESULTS)
        for name in self._mandatory_params:
            if name not in KNOWN_PARAMS_COLUMNS:
                raise ValueError(f'Unknown mandatory params column: {name!r}. Allowed: {sorted(KNOWN_PARAMS_COLUMNS)}')
        for name in self._mandatory_results:
            if name not in KNOWN_RESULT_COLUMNS:
                raise ValueError(f'Unknown mandatory result column: {name!r}. Allowed: {sorted(KNOWN_RESULT_COLUMNS)}')
        self._records: t.List[t.Dict[str, Any]] = []

        if self._auto_save and self._save_path:
            # Truncate any existing file so repeated runs start fresh.
            self._save_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_path.write_text('', encoding='utf-8')

    @property
    def records(self) -> t.List[t.Dict[str, Any]]:
        """Copy of currently collected records."""
        return [dict(r) for r in self._records]

    def __len__(self) -> int:
        return len(self._records)

    def add_record(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        params: t.Optional[t.Dict[str, Any]] = None,
        result: t.Optional[t.Dict[str, Any]] = None,
        *,
        duration: t.Optional[int] = None,
        logs: t.Optional[t.List[t.Dict[str, Any]]] = None,
        brief_message: t.Optional[str] = None,
        started_at: t.Optional[t.Union[datetime, str]] = None,
    ) -> t.Dict[str, Any]:
        """Validate and add one record.

        Args:
            params: Test parameters. Known keys in :data:`KNOWN_PARAMS_COLUMNS`
                are type-checked; unknown keys pass through.
            result: Test result values. Known keys in :data:`KNOWN_RESULT_COLUMNS`
                are type-checked; unknown keys pass through.
            duration: Optional duration in whatever unit the caller picks.
            logs: Optional list of collected log artifacts. Each entry is a
                dict describing one file and must contain exactly ``path`` (str)
                and ``type`` (str), e.g.
                ``[{"path": "/logs/stdout.log", "type": "log"},
                  {"path": "/logs/wifi.pcap",  "type": "pcap"}]``.
                Any key other than ``path`` / ``type`` is rejected.
            brief_message: Optional one-line human-readable summary.
            started_at: Optional start timestamp. ``datetime`` is serialized as
                ISO-8601 ``Z``; a ``str`` is stored verbatim.

        Raises:
            ValueError: A mandatory field is missing.
            TypeError:  A known field has the wrong type.
        """
        params = dict(params or {})
        result = dict(result or {})

        _validate_params(params, mandatory_params=self._mandatory_params)
        _validate_result(result, mandatory_results=self._mandatory_results)

        record: t.Dict[str, Any] = {
            'params': params,
            'result': result,
        }

        if duration is not None:
            assert isinstance(duration, int), 'duration must be int'
            record['duration'] = duration
        if logs is not None:
            assert isinstance(logs, list), 'logs must be a list'
            _validate_logs(logs)
            record['logs'] = logs
        if brief_message is not None:
            assert isinstance(brief_message, str), 'brief_message must be str'
            record['brief_message'] = brief_message
        if started_at is not None:
            if isinstance(started_at, datetime):
                record['started_at'] = _datetime_to_iso(started_at)
            elif isinstance(started_at, str):
                record['started_at'] = started_at
            else:
                raise TypeError(f'started_at must be datetime or ISO string, got {type(started_at).__name__}')

        self._records.append(record)
        if self._auto_save and self._save_path:
            self._append_one(record)
        return record

    def save(
        self,
        path: t.Optional[t.Union[str, Path]] = None,
        jsonl: bool = False,
        indent: t.Optional[int] = 2,
    ) -> Path:
        """Write all accumulated records to disk.

        Args:
            path:   Target file. Defaults to ``save_path`` from ``__init__``.
            jsonl: If True, write one JSON object per line (JSONL). Otherwise
                write a single JSON array.
            indent: ``json.dump`` indent (ignored in JSONL mode).

        Returns:
            The path written.
        """
        target = Path(path) if path else self._save_path
        if target is None:
            raise ValueError('save() requires a path argument or a save_path set in __init__')
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            if jsonl:
                for rec in self._records:
                    f.write(json.dumps(rec, ensure_ascii=False))
                    f.write('\n')
            else:
                json.dump(self._records, f, ensure_ascii=False, indent=indent)
        logger.debug('Saved %d performance result(s) to %s', len(self._records), target)
        return target

    def _append_one(self, record: t.Dict[str, Any]) -> None:
        """Append a single record as JSONL to ``self._save_path``."""
        if not self._save_path:
            return
        self._save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._save_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False))
            f.write('\n')


if __name__ == '__main__':  # pragma: no cover
    perf = PerformanceResult(
        mandatory_params=['target', 'type'],
        mandatory_results=['value'],
    )
    perf.add_record(
        params={'target': 'esp32', 'type': 'tcp_tx', 'att': 30, 'rssi': -65},
        result={'value': 100.5, 'suffix': 'Mbps'},
        duration=60,
        logs=[
            {'path': '/logs/stdout.log', 'type': 'log'},
            {'path': '/logs/wifi.pcap', 'type': 'pcap'},
        ],
        brief_message='success',
        started_at=datetime.now(timezone.utc),
    )
    perf.add_record(
        params={'target': 'esp32', 'type': 'tcp_rx', 'att': 30, 'rssi': -65},
        result={'value': 95.2, 'suffix': 'Mbps'},
        duration=60,
    )
    perf.save('performance_result.json')
