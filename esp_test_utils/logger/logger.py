import logging

module_logger = logging.getLogger('esp_test_utils')


def get_logger(suffix: str = '') -> logging.Logger:
    """get a child logger from esp_test_utils, returning the parent logger if suffix is not given."""
    if not suffix:
        return module_logger
    return module_logger.getChild(suffix)
