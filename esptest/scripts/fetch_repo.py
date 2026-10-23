#! /usr/bin/env python3
"""Command-line wrapper for :func:`esptest.tools.fetch_repo.fetch_repo`."""

import argparse
import logging
from typing import List, Optional

from esptest.tools.fetch_repo import fetch_repo


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Fetch git repository to local path')
    parser.add_argument('--url', required=True, help='Git repository URL')
    parser.add_argument('--path', required=True, help='Local repository path')
    parser.add_argument(
        '--ref',
        help='Branch/ref to clone/checkout (e.g. origin/master or chip/foo)',
    )
    parser.add_argument('--depth', type=int, default=0, help='Shallow fetch/clone depth, 0 means full history')
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(message)s')
    depth = args.depth if args.depth > 0 else 0
    logging.info(f'Fetching git repository {args.url} to {args.path} with ref {args.ref}, depth={depth}')
    fetch_repo(args.url, args.path, args.ref, depth=depth)


if __name__ == '__main__':
    main()
