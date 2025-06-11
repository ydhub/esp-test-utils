import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional, Union

try:
    # Run from `python -m esptest.tools.pip_check`
    from ..logger import get_logger
except ImportError:
    from esptest.logger import get_logger

logger = get_logger('pip_check')


def simple_check_requirements(
    requirements_file: Union[str, Path] = 'requirements.txt', _pkg_results: Optional[List[str]] = None
) -> bool:
    """Verify that installed packages meet the requirements specified in the requirements file.

    Args:
        requirements_file (str): Path to the requirements file. Default is 'requirements.txt'.

    Returns:
        bool: True if all requirements are met, False otherwise.

    Note:
        This function does not check package requirements specified by url.
    """
    if sys.version_info >= (3, 8):
        from importlib.metadata import PackageNotFoundError, version
    else:
        from pkg_resources import DistributionNotFound as PackageNotFoundError
        from pkg_resources import get_distribution

        def version(distribution_name: str) -> str:
            return get_distribution(distribution_name).version

    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.version import InvalidVersion, Version

    pkg_results = [] if _pkg_results is None else _pkg_results

    with open(requirements_file, 'r', encoding='utf-8') as f:
        for line in f:
            requirement = line.strip()
            if not requirement or requirement.startswith('#') or '//' in requirement:
                continue

            if requirement.startswith('-'):
                cmd, arg_line = requirement.split(maxsplit=1)
                if cmd in ['-r', '--requirement']:
                    # the file should be in absolute path or relative path to
                    # the current work directory
                    simple_check_requirements(arg_line, pkg_results)
                continue

            try:
                req = Requirement(requirement)
                try:
                    installed_version = Version(version(req.name))
                    if installed_version not in req.specifier:
                        pkg_results.append(
                            f"Package '{req.name}' version '{installed_version}' "
                            f'does not meet the requirement: {requirement}'
                        )
                except PackageNotFoundError:
                    pkg_results.append(f"Package '{requirement}' is not installed")
                except InvalidVersion:
                    pkg_results.append(f"Invalid version for package '{req.name}'")
            except InvalidRequirement:
                pkg_results.append(f"Invalid requirement format '{requirement}'")

    if _pkg_results is None and pkg_results:
        pkg_list = '\n  - ' + '\n  - '.join(pkg_results)
        logger.error(
            f'The following packages are not meet requiremtents:{pkg_list}\n'
            f'Please run "pip install -r {requirements_file}" '
            f'to update the dependencies'
        )
        return False
    return True


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser(description='Check pip requirements')
    parser.add_argument('requirements_files', type=str, help='requirements file')
    args = parser.parse_args()

    simple_check_requirements(args.requirements_files)


if __name__ == '__main__':
    main()
