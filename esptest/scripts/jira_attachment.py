#! /usr/bin/env python3
"""Manage Jira issue attachments."""

import argparse
import logging
import os

import esptest.common.compat_typing as t
from esptest.jira import (
    create_client,
    download_all_attachments,
    download_attachment,
    list_attachments,
    login_jira,
    upload_attachments,
)


def parse_args(argv: t.Optional[t.List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Upload, download, or list Jira issue attachments.')
    parser.add_argument('--server', help='Override the Jira server URL.')
    parser.add_argument('--token', help='Override the Jira personal access token.')
    parser.add_argument('--timeout', type=int, default=1200, help='Jira request timeout in seconds (default: 1200).')

    commands = parser.add_subparsers(dest='command', required=True)

    upload_parser = commands.add_parser('upload', help='Upload files or directories to a Jira issue.')
    upload_parser.add_argument('issue', help='Jira issue key.')
    upload_parser.add_argument('paths', nargs='+', help='Files or directories to upload.')
    upload_parser.add_argument('--name', help='Attachment name; valid only with one path.')

    download_parser = commands.add_parser('download', help='Download one or all Jira issue attachments.')
    download_parser.add_argument('issue', help='Jira issue key.')
    selector = download_parser.add_mutually_exclusive_group()
    selector.add_argument('--name', help='Download the attachment with this filename.')
    selector.add_argument('--id', dest='attachment_id', help='Download the attachment with this Jira attachment ID.')
    download_parser.add_argument(
        '--dest',
        default='.',
        help='Destination directory. Defaults to the current directory.',
    )

    list_parser = commands.add_parser('list', help='List Jira issue attachments.')
    list_parser.add_argument('issue', help='Jira issue key.')
    return parser.parse_args(argv)


def _client_from_args(args: argparse.Namespace) -> t.Any:
    if args.server or args.token or args.timeout != 1200:
        return create_client(server=args.server, token=args.token, timeout=args.timeout)
    return login_jira()


def main(argv: t.Optional[t.List[str]] = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    client = _client_from_args(args)

    if args.command == 'upload':
        uploaded = upload_attachments(client, args.issue, args.paths, filename=args.name)
        logging.info('Uploaded %d attachment(s) to %s.', len(uploaded), args.issue)
    elif args.command == 'download':
        destination_dir = os.path.expanduser(args.dest)
        if args.name or args.attachment_id:
            filename = args.name
            if args.attachment_id:
                attachment = next(
                    (info for info in list_attachments(client, args.issue) if info.id == str(args.attachment_id)),
                    None,
                )
                if attachment is None:
                    raise FileNotFoundError('Jira attachment {} was not found'.format(args.attachment_id))
                filename = attachment.filename
            assert filename is not None
            destination = os.path.join(destination_dir, os.path.basename(filename))
            downloaded = download_attachment(
                client,
                args.issue,
                destination,
                attachment_name=args.name,
                attachment_id=args.attachment_id,
            )
            logging.info('Downloaded %s.', downloaded)
        else:
            downloaded = download_all_attachments(client, args.issue, destination_dir)
            logging.info('Downloaded %d attachment(s) to %s.', len(downloaded), destination_dir)
    else:
        for attachment in list_attachments(client, args.issue):
            print('{}\t{}\t{}'.format(attachment.id, attachment.size, attachment.filename))


if __name__ == '__main__':
    main()
