import re
import threading
import time

import esptest.common.compat_typing as t

from .encoding import to_str


class _DataCache:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.data = ''


class MatchedResult:
    def __init__(
        self,
        key: str,
        port_name: str = '',
        match: t.Optional[t.Union['re.Match[str]', str]] = None,
        timestamp: float = 0,
    ) -> None:
        self.key = key
        self.port_name = port_name
        self.match = match
        self.timestamp = timestamp

    def __str__(self) -> str:
        return (
            f'MatchedResult(key={self.key}, port_name={self.port_name}, match={self.match}, timestamp={self.timestamp})'
        )


class DataMonitor:
    def __init__(
        self,
        pattern: t.Union[str, 're.Pattern[str]'],
        # callback(key,name,match,time)
        callback: t.Optional[t.Callable[[MatchedResult], None]] = None,
        # monitor on specific port names
        port_names: t.Optional[t.List[str]] = None,
    ) -> None:
        """
        callback: (matched_result)
        """
        self._pattern = pattern
        if isinstance(pattern, re.Pattern):
            self._key = pattern.pattern
        else:
            self._key = pattern
        self._callback = callback
        self._port_names = port_names or []
        # self._matched_results = []
        # data cache
        self._data_cache: t.Dict[str, _DataCache] = {}
        self._data_cache_lock = threading.Lock()
        # shared matched states across ports
        self._matched_lock = threading.Lock()
        # matched results
        self.matched_count = 0
        self.matched_ports: t.List[str] = []
        self.matched_results: t.List[MatchedResult] = []

    @property
    def key(self) -> str:
        return self._key

    @property
    def pattern(self) -> t.Union[str, 're.Pattern[str]']:
        return self._pattern

    def __str__(self) -> str:
        return f'DataMonitor(key={self.key}, pattern={self.pattern}, port_names={self._port_names})'

    def __hash__(self) -> int:
        _s = f'{self.key}-{id(self._callback)}-{self._port_names}'
        return hash(_s)

    def __eq__(self, other: t.Any) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return hash(self) == hash(other) and self.pattern == other.pattern

    def _check_pattern(
        self,
        data: str,
        pattern: t.Union[str, 're.Pattern[str]'],
    ) -> t.Tuple[t.Optional[t.Union['re.Match[str]', str]], int]:
        """
        return matched, pos
        """
        if isinstance(pattern, re.Pattern):
            match = pattern.search(data)
            if not match:
                return None, 0
            return match, match.end()

        pos = data.find(pattern)
        if pos < 0:
            return None, 0
        return pattern, pos + len(pattern)

    def append_data(self, port_name: str, data: t.AnyStr, timestamp: float = 0) -> None:
        if self._port_names and port_name not in self._port_names:
            return
        if timestamp == 0:
            timestamp = time.time()
        with self._data_cache_lock:
            data_cache = self._data_cache.get(port_name)
            if data_cache is None:
                data_cache = _DataCache()
                self._data_cache[port_name] = data_cache

        with data_cache.lock:
            data_cache.data += to_str(data)
            # consume all matches available in current accumulated cache
            matched, pos = self._check_pattern(data_cache.data, self._pattern)
            while matched:
                matched_result = MatchedResult(self._key, port_name, matched, timestamp)
                with self._matched_lock:
                    self.matched_count += 1
                    self.matched_ports.append(port_name)
                    self.matched_results.append(matched_result)
                # trim data cache
                before_trim_data = data_cache.data
                if pos <= 0:
                    pos = 1
                data_cache.data = data_cache.data[pos:]
                if self._callback:
                    self._callback(matched_result)
                if data_cache.data == before_trim_data:
                    break
                matched, pos = self._check_pattern(data_cache.data, self._pattern)
