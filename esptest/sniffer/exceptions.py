class SnifferError(Exception):
    """Base exception for all sniffer operation failures."""
    pass


class SnifferConnectionError(SnifferError):
    """Failed to connect to the Ellisys analyzer application."""
    pass


class SnifferRecordingError(SnifferError):
    """A recording operation (start, stop, abort) failed."""
    pass
