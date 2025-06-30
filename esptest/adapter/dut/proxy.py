import esptest.common.compat_typing as t

T = t.TypeVar('T')


class PortProxy(t.Generic[T]):
    def __init__(self, target: T, attrs: t.Optional[t.List[str]] = None):
        self._attrs = attrs or []
        self._target = target

    def __getattribute__(self, name: str) -> t.Any:
        if not self._attrs:
            return getattr(self._target, name)
        if name in self._attrs:
            return getattr(self._target, name)
        return super().__getattribute__(name)
