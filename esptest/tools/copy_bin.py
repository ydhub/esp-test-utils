import argparse
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

try:
    # from import or `python -m esptest.tools.pip_check`
    from ..logger import get_logger

    logger = get_logger('copy_bin')
except ImportError:
    logger = logging.getLogger('copy_bin')

IDF_PATH = os.getenv('IDF_PATH', '')


class BuildFilesPatterns:
    BIN_FILES = [
        '*.bin',
        'bootloader/*.bin',
        'partition_table/*.bin',
        'partition_table/*.csv',
        'flasher_args.json',
        'flash_project_args',
        'config/sdkconfig.json',
        'sdkconfig',
    ]
    # For extra debugging
    MAP_AND_ELF_FILES = [
        'project_description.json',
        'bootloader/*.map',
        'bootloader/*.elf',
        '*.map',
        '*.elf',
    ]


def copy_bin_to_new_path(
    from_dir: str,
    to_path: str,
    *,
    zip_output: bool = False,
    force: bool = True,
    copy_elf: bool = True,
    extra_files: Optional[List[str]] = None,
) -> None:
    """Copy build files to new path

    Args:
        from_dir (str): the app build directory. eg: ./build/
        to_path (str): Destination directory or zip file to save the bin files.
        zip_output (bool, optional): Zip the destination directory. Defaults to False.
        force (bool, optional): Delete the destination dir if it is already exists. Defaults to True.
        copy_elf (bool, optional): Copy elf and map files as well. Defaults to True.
        extra_files (Optional[List[str]], optional): . Defaults to None.
    """
    from_path = Path(from_dir).resolve().absolute()
    to_path_obj = Path(to_path).resolve().absolute()
    assert from_path.is_dir()
    if force and to_path_obj.exists():
        logger.debug(f'Removing existing destination directory or file {to_path_obj}')
        if to_path_obj.is_dir():
            shutil.rmtree(str(to_path_obj))
        else:
            to_path_obj.unlink()
    if zip_output:
        assert to_path_obj.suffix == '.zip'
        to_path_obj.parent.mkdir(parents=True, exist_ok=True)
        to_dir = Path(tempfile.mkdtemp())
    else:
        to_dir = to_path_obj
        to_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f'Copying bin files from {from_path} to {to_path_obj}')

    all_patterns = BuildFilesPatterns.BIN_FILES
    if copy_elf:
        all_patterns.extend(BuildFilesPatterns.MAP_AND_ELF_FILES)
    if extra_files:
        all_patterns.extend(extra_files)

    for pattern in all_patterns:
        for _file in from_path.glob(pattern):
            assert _file.is_file()
            relative_path = _file.relative_to(from_path)
            to_file = to_dir / relative_path
            if not to_file.parent.is_dir():
                to_file.parent.mkdir(parents=True)
            logging.debug(f'Copying file {relative_path}')
            shutil.copy(_file, to_dir / relative_path)

    # parse 'partition-table.bin'
    if IDF_PATH:
        part_csv = Path(to_dir) / 'partition_table' / 'partition-table.csv'
        part_bin = Path(to_dir) / 'partition_table' / 'partition-table.bin'
        parttool = Path(IDF_PATH) / 'components' / 'partition_table' / 'gen_esp32part.py'
        if not part_csv.is_file() and part_bin.is_file():
            assert parttool.is_file(), 'Can not find gen_esp32part.py'
            try:
                _cmd = ['python', str(parttool.absolute()), str(part_bin), str(part_csv)]
                subprocess.check_call(_cmd, shell=False)
            except subprocess.SubprocessError as e:
                logger.error(f'Failed to gen partition-table.csv: {str(e)}')
    # zip the destination directory
    if zip_output:
        shutil.make_archive(str(to_path_obj.with_suffix('')), 'zip', root_dir=str(to_dir))
        shutil.rmtree(str(to_dir))


def main() -> None:
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser(description='Copy bin files')
    parser.add_argument('from_dir', type=str, help='source directory of build bin files')
    parser.add_argument('to_path', type=str, help='destination directory or zip file')
    parser.add_argument(
        '--zip',
        action='store_true',
        help='zip destination, and to_path should end with .zip',
    )
    args = parser.parse_args()

    copy_bin_to_new_path(args.from_dir, args.to_path, zip_output=args.zip)


if __name__ == '__main__':
    main()
