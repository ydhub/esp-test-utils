import logging

module_logger = logging.getLogger('esptest')


def get_logger(suffix: str = '') -> logging.Logger:
    """get a child logger from esptest, returning the parent logger if suffix is not given."""
    if not suffix:
        return module_logger
    return module_logger.getChild(suffix)


class MultiLineFormatter(logging.Formatter):
    """indent for multiple lines

    logging output:

    ::

        [2025-06-10 13:05:17] INFO - This is a message
            Line 2
            Line 3

    """

    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)
        return s.replace('\n', '\n    ')
