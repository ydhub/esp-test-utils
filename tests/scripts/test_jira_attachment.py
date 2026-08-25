from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from esptest.jira import AttachmentInfo
from esptest.scripts import jira_attachment


def test_parse_args_accepts_upload() -> None:
    args = jira_attachment.parse_args(['upload', 'TEST-1', 'log.txt', '--name', 'renamed.txt'])

    assert args.command == 'upload'
    assert args.issue == 'TEST-1'
    assert args.paths == ['log.txt']
    assert args.name == 'renamed.txt'


def test_main_uploads_paths() -> None:
    args = SimpleNamespace(
        command='upload',
        issue='TEST-1',
        paths=['log.txt'],
        name=None,
        server=None,
        token=None,
        timeout=1200,
    )
    client = object()

    with mock.patch.object(jira_attachment, 'parse_args', return_value=args):
        with mock.patch.object(jira_attachment, 'login_jira', return_value=client):
            with mock.patch.object(jira_attachment, 'upload_attachments', return_value=[object()]) as upload:
                jira_attachment.main()

    upload.assert_called_once_with(client, 'TEST-1', ['log.txt'], filename=None)


def test_main_downloads_all_to_destination(tmp_path: Path) -> None:
    args = SimpleNamespace(
        command='download',
        issue='TEST-1',
        name=None,
        attachment_id=None,
        dest=str(tmp_path),
        server=None,
        token=None,
        timeout=1200,
    )
    client = object()

    with mock.patch.object(jira_attachment, 'parse_args', return_value=args):
        with mock.patch.object(jira_attachment, 'login_jira', return_value=client):
            with mock.patch.object(jira_attachment, 'download_all_attachments', return_value=['a', 'b']) as download:
                jira_attachment.main()

    download.assert_called_once_with(client, 'TEST-1', str(tmp_path))


def test_main_downloads_attachment_id_with_original_filename(tmp_path: Path) -> None:
    args = SimpleNamespace(
        command='download',
        issue='TEST-1',
        name=None,
        attachment_id='12',
        dest=str(tmp_path),
        server=None,
        token=None,
        timeout=1200,
    )
    client = object()

    with mock.patch.object(jira_attachment, 'parse_args', return_value=args):
        with mock.patch.object(jira_attachment, 'login_jira', return_value=client):
            with mock.patch.object(
                jira_attachment, 'list_attachments', return_value=[AttachmentInfo('12', 'log.txt', 3)]
            ):
                with mock.patch.object(
                    jira_attachment, 'download_attachment', return_value='output/log.txt'
                ) as download:
                    jira_attachment.main()

    download.assert_called_once_with(
        client,
        'TEST-1',
        str(tmp_path / 'log.txt'),
        attachment_name=None,
        attachment_id='12',
    )


def test_main_lists_attachments(capsys: pytest.CaptureFixture[str]) -> None:
    args = SimpleNamespace(
        command='list',
        issue='TEST-1',
        server=None,
        token=None,
        timeout=1200,
    )
    client = object()

    with mock.patch.object(jira_attachment, 'parse_args', return_value=args):
        with mock.patch.object(jira_attachment, 'login_jira', return_value=client):
            with mock.patch.object(
                jira_attachment, 'list_attachments', return_value=[AttachmentInfo('12', 'log.txt', 3)]
            ):
                jira_attachment.main()

    assert capsys.readouterr().out == '12\t3\tlog.txt\n'


def test_main_parses_list_arguments_without_reparsing_defaults(capsys: pytest.CaptureFixture[str]) -> None:
    client = object()

    with mock.patch.object(jira_attachment, 'login_jira', return_value=client):
        with mock.patch.object(jira_attachment, 'list_attachments', return_value=[AttachmentInfo('12', 'log.txt', 3)]):
            jira_attachment.main(['list', 'TEST-1'])

    assert capsys.readouterr().out == '12\t3\tlog.txt\n'
