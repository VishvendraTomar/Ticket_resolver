"""Document parsing interface. Implementations: fake (tests), docling (worker).

A parser turns file bytes into an ordered list of blocks that keep structure
(headings with levels, paragraphs, tables as Markdown). Sectioning and chunking
are ours (app/ingestion) and work on these blocks only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"


# Formats we accept (checked from magic bytes at upload, docs/failure-modes/ingestion.md #2).
MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_HTML = "text/html"
MIME_MARKDOWN = "text/markdown"
SUPPORTED_MIME_TYPES = (MIME_PDF, MIME_DOCX, MIME_HTML, MIME_MARKDOWN)


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    # Headings: 0 = document title, 1 = top-level section, 2 = subsection, ...
    level: int | None = None
    page: int | None = None


@dataclass(frozen=True)
class ParsedDocument:
    blocks: list[Block]
    parser: str  # name and version, recorded in the parse report
    page_count: int | None = None
    # OCR confidence per page (0..1), only for pages that were OCR'd.
    ocr_confidence: dict[int, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class ParseError(Exception):
    """The file couldn't be parsed. The message is shown to editors."""


class Parser(Protocol):
    def parse(self, data: bytes, mime_type: str, file_name: str) -> ParsedDocument:
        """Synchronous and CPU-bound: runs inside the ingestion worker."""
        ...
