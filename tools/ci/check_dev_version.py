import os
import sys

from packaging.version import Version

PUBLISH_DEV_VERSION = os.getenv('PUBLISH_DEV_VERSION')


def check_dev_version() -> None:
    if not PUBLISH_DEV_VERSION:
        return
    if PUBLISH_DEV_VERSION == 'auto':
        return
    try:
        ver = Version(PUBLISH_DEV_VERSION)
        if ver.is_devrelease or ver.is_prerelease:
            return
        print('PUBLISH_DEV_VERSION must be dev or pre, eg:')
        print(' - 1.2.3a1')
        print(' - 1.2.3.dev2')
    except ValueError:
        print(f'Invailed Version: {PUBLISH_DEV_VERSION}')
        sys.exit(1)


if __name__ == '__main__':
    check_dev_version()
