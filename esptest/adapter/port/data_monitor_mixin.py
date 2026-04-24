from typing import TYPE_CHECKING

import esptest.common.compat_typing as t

from ...common.data_monitor import DataMonitor

if TYPE_CHECKING:

    class _SupportsMonitors(t.Protocol):
        @property
        def monitors(self) -> t.List[DataMonitor]: ...

        @monitors.setter
        def monitors(self, new_monitors: t.List[DataMonitor]) -> None: ...

else:
    _SupportsMonitors = object


class DataMonitorMixin(_SupportsMonitors):
    def add_monitor(self, monitor: DataMonitor) -> None:
        new_monitors = list(self.monitors)
        if monitor in new_monitors:
            return
        new_monitors.append(monitor)
        self.monitors = new_monitors

    def remove_monitor(self, monitor: DataMonitor) -> None:
        new_monitors = list(self.monitors)
        if monitor not in new_monitors:
            return
        new_monitors.remove(monitor)
        self.monitors = new_monitors

    def clear_monitors(self) -> None:
        self.monitors = []
