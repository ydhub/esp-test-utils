#! /usr/bin/env python3

import argparse
import logging
import os
import shutil
import subprocess
from typing import Any, List, Optional


def run_cmd(cmd: List[str], **kwargs: Any) -> None:
    logging.debug(f'Running command: {" ".join(cmd)}')
    subprocess.run(cmd, check=True, **kwargs)


def check_git_repo(repo_path: str) -> None:
    if not os.path.isdir(repo_path):
        return

    git_dir = os.path.join(repo_path, '.git')
    if not os.path.isdir(git_dir):
        # path is not a git repository, remove it
        shutil.rmtree(repo_path)
        return

    try:
        run_cmd(['git', '-C', repo_path, 'rev-parse', '--git-dir'])
    except subprocess.CalledProcessError:
        logging.error(f'Git repo {repo_path} corrupted, removing...')
        shutil.rmtree(repo_path)


def fetch_repo(url: str, path: str, ref: str, depth: Optional[int] = None) -> None:
    check_git_repo(path)

    # ref not set, clone default branch
    if not ref:
        if os.path.isdir(path):
            # path is a git repository, but no ref provided
            logging.warning(f'Path {path} already exists, but no ref provided, skipping fetch...')
            return
        # clone repo from remote url with default branch
        clone_args = ['git', 'clone', url, path]
        if depth:
            clone_args.extend(['--depth', str(depth)])
        run_cmd(clone_args)
        return

    # fetch specific ref
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        init_args = ['git', '-C', path, 'init']
        run_cmd(init_args)

    # path is a git repository, configure remote origin url and fetch
    # ref may be a branch, tag or commit hash.
    # always checkout to new branch with FETCH_HEAD
    run_cmd(['git', '-C', path, 'config', 'remote.origin.url', url])
    # refspec = f'refs/heads/{ref}:refs/remotes/origin/{ref}'
    fetch_args = ['git', '-C', path, 'fetch', 'origin', ref]
    if depth:
        fetch_args.extend(['--depth', str(depth)])
    run_cmd(fetch_args)
    run_cmd(['git', '-C', path, 'checkout', '-f', '-B', ref, 'FETCH_HEAD'])
    run_cmd(['git', '-C', path, 'reset', '--hard'])
    run_cmd(['git', '-C', path, 'clean', '-ffdx'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
