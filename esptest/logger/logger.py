import logging

module_logger = logging.getLogger('esptest')


def get_logger(suffix: str = '') -> logging.Logger:
    """get a child logger from esptest, returning the parent logger if suffix is not given."""
    if not suffix:
        return module_logger
    return module_logger.getChild(suffix)
