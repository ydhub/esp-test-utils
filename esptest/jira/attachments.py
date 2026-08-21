"""Upload, list, and download Jira issue attachments."""

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import esptest.common.compat_typing as t

EVIDENCE_MAX_SIZE = 20 * 1024 * 1024


@dataclass(frozen=True)
class AttachmentInfo:
    """Metadata for an attachment associated with a Jira issue."""

    id: str
    filename: str
    size: int


def _attachment_info(attachment: t.Any) -> AttachmentInfo:
    return AttachmentInfo(
        id=str(attachment.id),
        filename=str(attachment.filename),
        size=int(getattr(attachment, 'size', 0)),
    )


def list_attachments(client: t.Any, issue_key: str) -> t.List[AttachmentInfo]:
    """List attachment metadata for an issue."""
    issue = client.issue(issue_key)
    return [_attachment_info(attachment) for attachment in issue.fields.attachment]


def _issue_attachments(client: t.Any, issue_key: str) -> t.List[t.Any]:
    return list(client.issue(issue_key).fields.attachment)


def _zip_directory(source: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix='esp-jira-attachment-'))
    archive = temp_dir / '{}.zip'.format(source.name)
    file_count = 0
    with zipfile.ZipFile(str(archive), 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zip_file:
        for root, _directories, filenames in os.walk(str(source)):
            for filename in filenames:
                source_file = Path(root) / filename
                zip_file.write(str(source_file), str(source_file.relative_to(source.parent)))
                file_count += 1

    if not file_count:
        shutil.rmtree(str(temp_dir))
        raise OSError('evidence directory contains no files')
    if archive.stat().st_size > EVIDENCE_MAX_SIZE:
        shutil.rmtree(str(temp_dir))
        raise OSError('evidence result file too large (maximum is 20 MiB)')
    return archive


def upload_attachments(
    client: t.Any,
    issue_key: str,
    paths: t.Sequence[t.Union[str, os.PathLike]],
    filename: t.Optional[str] = None,
) -> t.List[t.Any]:
    """Upload files or zipped directories to an issue.

    A supplied filename applies only when exactly one path is uploaded, avoiding
    indistinguishable names for multiple attachments.
    """
    if not paths:
        raise ValueError('at least one attachment path is required')
    if filename and len(paths) != 1:
        raise ValueError('--name can only be used when uploading one path')

    uploaded = []
    for item in paths:
        source = Path(item)
        if not source.exists():
            raise FileNotFoundError(str(source))
        if not source.is_file() and not source.is_dir():
            raise ValueError('{} is neither a file nor a directory'.format(source))

        temporary_archive = source.is_dir()
        attachment = _zip_directory(source) if temporary_archive else source
        try:
            uploaded.append(
                client.add_attachment(
                    issue=issue_key,
                    attachment=str(attachment),
                    filename=filename or attachment.name,
                )
            )
        finally:
            if temporary_archive:
                shutil.rmtree(str(attachment.parent), ignore_errors=True)
    return uploaded


def _find_attachment(
    attachments: t.Iterable[t.Any],
    attachment_name: t.Optional[str] = None,
    attachment_id: t.Optional[str] = None,
) -> t.Any:
    if bool(attachment_name) == bool(attachment_id):
        raise ValueError('specify exactly one of attachment_name or attachment_id')
    for attachment in attachments:
        if attachment_name and attachment.filename == attachment_name:
            return attachment
        if attachment_id and str(attachment.id) == str(attachment_id):
            return attachment
    target = attachment_name or attachment_id
    raise FileNotFoundError('Jira attachment {} was not found'.format(target))


def download_attachment(
    client: t.Any,
    issue_key: str,
    destination: t.Union[str, os.PathLike],
    attachment_name: t.Optional[str] = None,
    attachment_id: t.Optional[str] = None,
) -> str:
    """Download one selected attachment to an exact destination file path."""
    attachment = _find_attachment(_issue_attachments(client, issue_key), attachment_name, attachment_id)
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(attachment.get())
    return str(output)


def _unique_destination(directory: Path, filename: str) -> Path:
    safe_filename = Path(filename).name
    if not safe_filename:
        raise ValueError('Jira attachment has no valid filename')
    candidate = directory / safe_filename
    index = 1
    while candidate.exists():
        candidate = directory / '{} ({}){}'.format(Path(safe_filename).stem, index, Path(safe_filename).suffix)
        index += 1
    return candidate


def download_all_attachments(
    client: t.Any,
    issue_key: str,
    destination_dir: t.Union[str, os.PathLike],
) -> t.List[str]:
    """Download all issue attachments, preserving each attachment's filename."""
    output_dir = Path(destination_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destinations = []
    for attachment in _issue_attachments(client, issue_key):
        output = _unique_destination(output_dir, attachment.filename)
        output.write_bytes(attachment.get())
        destinations.append(str(output))
    return destinations
