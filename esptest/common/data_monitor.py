import re
import threading

import esptest.common.compat_typing as t

from .encoding import to_str


class _DataCache:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.data = ''


class DataMonitor:
    def __init__(
        self,
        pattern: t.Union[str, re.Pattern[str]],
        # callback(key,name,match,time)
        callback: t.Optional[t.Callable[[str, str, t.Optional[re.Match[str]], float], None]] = None,
        # monitor on specific port names
        port_names: t.Optional[t.List[str]] = None,
    ) -> None:
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

    @property
    def key(self) -> str:
        return self._key

    def __hash__(self) -> int:
        _s = f'{self.key}-{id(self._callback)}-{self._port_names}'
        return hash(_s)

    def append_data(self, port_name: str, data: t.AnyStr, ts: float = 0) -> None:
        if self._port_names and port_name not in self._port_names:
            return
        if port_name not in self._data_cache:
            self._data_cache[port_name] = _DataCache()
        with self._data_cache[port_name].lock:
            self._data_cache[port_name].data += to_str(data)
        # TODO: matched
        if self._callback:
            self._callback(self._key, '', None, ts)
