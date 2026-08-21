from types import SimpleNamespace

import pytest

from esptest.jira.attachments import (
    download_all_attachments,
    download_attachment,
    list_attachments,
    upload_attachments,
)


class FakeAttachment:
    def __init__(self, attachment_id: str, filename: str, content: bytes, size: int = 0) -> None:
        self.id = attachment_id
        self.filename = filename
        self.size = size or len(content)
        self._content = content

    def get(self) -> bytes:
        return self._content


class FakeClient:
    def __init__(self, attachments=None) -> None:
        self.attachments = attachments or []
        self.uploads = []

    def issue(self, issue_key: str):
        assert issue_key == 'TEST-1'
        return SimpleNamespace(fields=SimpleNamespace(attachment=self.attachments))

    def add_attachment(self, **kwargs):
        self.uploads.append(kwargs)
        return kwargs


def test_list_attachments_returns_metadata() -> None:
    client = FakeClient([FakeAttachment('12', 'log.txt', b'log', size=3)])

    attachments = list_attachments(client, 'TEST-1')

    assert attachments[0].id == '12'
    assert attachments[0].filename == 'log.txt'
    assert attachments[0].size == 3


def test_upload_file_forwards_custom_filename(tmp_path) -> None:
    source = tmp_path / 'log.txt'
    source.write_text('content')
    client = FakeClient()

    upload_attachments(client, 'TEST-1', [source], filename='renamed.txt')

    assert client.uploads == [
        {
            'issue': 'TEST-1',
            'attachment': str(source),
            'filename': 'renamed.txt',
        }
    ]


def test_upload_directory_zips_and_cleans_temporary_archive(tmp_path) -> None:
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    (evidence / 'result.log').write_text('result')
    client = FakeClient()

    upload_attachments(client, 'TEST-1', [evidence])

    uploaded_path = client.uploads[0]['attachment']
    assert client.uploads[0]['filename'] == 'evidence.zip'
    assert not tmp_path.joinpath(uploaded_path).exists()


def test_download_attachment_by_id(tmp_path) -> None:
    client = FakeClient([FakeAttachment('12', 'log.txt', b'content')])
    destination = tmp_path / 'downloaded.log'

    result = download_attachment(client, 'TEST-1', destination, attachment_id='12')

    assert result == str(destination)
    assert destination.read_bytes() == b'content'


def test_download_all_preserves_duplicate_filenames(tmp_path) -> None:
    client = FakeClient(
        [
            FakeAttachment('1', 'log.txt', b'first'),
            FakeAttachment('2', 'log.txt', b'second'),
            FakeAttachment('3', '../unsafe.txt', b'safe'),
        ]
    )

    downloaded = download_all_attachments(client, 'TEST-1', tmp_path)

    assert [item.split('/')[-1] for item in downloaded] == ['log.txt', 'log (1).txt', 'unsafe.txt']
    assert (tmp_path / 'log.txt').read_bytes() == b'first'
    assert (tmp_path / 'log (1).txt').read_bytes() == b'second'
    assert (tmp_path / 'unsafe.txt').read_bytes() == b'safe'


def test_upload_rejects_custom_name_for_multiple_files(tmp_path) -> None:
    first = tmp_path / 'one.txt'
    second = tmp_path / 'two.txt'
    first.touch()
    second.touch()

    with pytest.raises(ValueError, match='one path'):
        upload_attachments(FakeClient(), 'TEST-1', [first, second], filename='same.txt')
