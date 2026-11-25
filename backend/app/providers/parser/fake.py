"""Deterministic parser for tests: reads Markdown-like text from any file type.

`#` headings (one # = title, ## = level 1, ...), `|` lines form one table block,
`- ` lines are list items, blank lines separate paragraphs. Tests can preset OCR
confidence, page counts or a failure.
"""

from __future__ import annotations

from app.providers.parser.base import Block, BlockKind, ParsedDocument, ParseError


class FakeParser:
    def __init__(
        self,
        *,
        ocr_confidence: dict[int, float] | None = None,
        page_count: int | None = None,
        fail_with: str | None = None,
    ) -> None:
        self.ocr_confidence = ocr_confidence or {}
        self.page_count = page_count
        self.fail_with = fail_with
        self.calls = 0

    def parse(self, data: bytes, mime_type: str, file_name: str) -> ParsedDocument:
        self.calls += 1
        if self.fail_with:
            raise ParseError(self.fail_with)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParseError("fake parser only reads UTF-8 text") from exc
        return ParsedDocument(
            blocks=parse_markdown(text),
            parser="fake-markdown 1",
            page_count=self.page_count,
            ocr_confidence=dict(self.ocr_confidence),
        )


def parse_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    para: list[str] = []
    table: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(Block(BlockKind.PARAGRAPH, " ".join(para)))
            para.clear()
        if table:
            blocks.append(Block(BlockKind.TABLE, "\n".join(table)))
            table.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            if para:
                blocks.append(Block(BlockKind.PARAGRAPH, " ".join(para)))
                para.clear()
            table.append(line)
            continue
        if table:
            blocks.append(Block(BlockKind.TABLE, "\n".join(table)))
            table.clear()
        if not line:
            flush()
        elif line.startswith("#"):
            flush()
            hashes = len(line) - len(line.lstrip("#"))
            blocks.append(Block(BlockKind.HEADING, line[hashes:].strip(), level=hashes - 1))
        elif line.startswith(("- ", "* ")):
            flush()
            blocks.append(Block(BlockKind.LIST_ITEM, line[2:].strip()))
        else:
            para.append(line)
    flush()
    return blocks
