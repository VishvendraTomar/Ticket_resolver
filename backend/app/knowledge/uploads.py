"""Upload checks: size and type from the bytes themselves (failure-modes/ingestion.md #2)."""

from __future__ import annotations

import hashlib
import io
import zipfile

from app.core.errors import PayloadTooLarge, UnsupportedMediaType
from app.providers.parser.base import MIME_DOCX, MIME_HTML, MIME_MARKDOWN, MIME_PDF

EXTENSIONS = {MIME_PDF: ".pdf", MIME_DOCX: ".docx", MIME_HTML: ".html", MIME_MARKDOWN: ".md"}


def check_size(data: bytes, max_mb: int) -> None:
    if len(data) > max_mb * 1024 * 1024:
        raise PayloadTooLarge(f"File is larger than {max_mb} MB")
    if not data:
        raise UnsupportedMediaType("File is empty")


def detect_mime(data: bytes, file_name: str) -> str:
    """PDF, DOCX, HTML or Markdown, judged by content. The name only breaks text ties."""
    if data.startswith(b"%PDF-"):
        return MIME_PDF
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return MIME_DOCX
        except zipfile.BadZipFile:
            pass
        raise UnsupportedMediaType("Unsupported file type (only PDF, DOCX, HTML, Markdown)")
    try:
        text = data[:4096].decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnsupportedMediaType(
            "Unsupported file type (only PDF, DOCX, HTML, Markdown)"
        ) from exc
    head = text.lstrip().lower()
    if head.startswith(("<!doctype html", "<html")) or "<body" in head[:2048]:
        return MIME_HTML
    if file_name.lower().endswith((".md", ".markdown", ".txt")):
        return MIME_MARKDOWN
    raise UnsupportedMediaType("Text files must be Markdown (.md) or HTML")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def storage_key(workspace_id: object, file_hash: str, mime_type: str) -> str:
    # Content-addressed per workspace: re-uploading the same bytes overwrites nothing new.
    return f"workspaces/{workspace_id}/originals/{file_hash}{EXTENSIONS[mime_type]}"
