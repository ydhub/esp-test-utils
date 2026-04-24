import os


class DefaultConfig:
    # default port expect timeout
    PORT_EXPECT_TIMEOUT = int(os.environ.get('ESPTEST_PORT_EXPECT_TIMEOUT', 30))

    # older data cache will be discarded if it is larger than 2x limit
    DATA_CACHE_SIZE_LIMIT = int(os.environ.get('ESPTEST_DATA_CACHE_SIZE_LIMIT', 1 * 1024 * 1024))

    # port spawn maxread size, max buffer read for expect process, default 10K
    PORT_SPAWN_MAXREAD = int(os.environ.get('ESPTEST_PORT_SPAWN_MAXREAD', 10 * 1024))

    # allow serial read-thread error reconnect attempts
    ALLOW_SERIAL_ERROR_RECONNECT_COUNT = int(os.environ.get('ESPTEST_ALLOW_SERIAL_ERROR_RECONNECT_COUNT', 0))


g = DefaultConfig()
