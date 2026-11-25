"""The real Docling parser (ADR-0006). Markdown/HTML/DOCX need no ML models; PDF+OCR
needs Docling's model download, so it is marked `docling_models` and runs only with
DOCLING_MODELS=1."""

from __future__ import annotations

import io
import os

import pytest

from app.providers.parser.base import (
    MIME_DOCX,
    MIME_HTML,
    MIME_MARKDOWN,
    MIME_PDF,
    BlockKind,
    ParseError,
)
from app.providers.parser.docling import DoclingParser

POLICY = """# Leave Policy

## 4. Annual leave

4.1 Employees get 30 days. See Annex B.

| Years | Days |
|---|---|
| 0-5 | 30 |

## Annex B

Forms.
"""


@pytest.fixture(scope="module")
def parser() -> DoclingParser:
    return DoclingParser(max_pages=300, timeout_seconds=120)


def test_markdown(parser: DoclingParser) -> None:
    doc = parser.parse(POLICY.encode(), MIME_MARKDOWN, "p.md")
    kinds = [(b.kind, b.level) for b in doc.blocks]
    assert kinds[:2] == [(BlockKind.HEADING, 0), (BlockKind.HEADING, 1)]
    table = next(b for b in doc.blocks if b.kind is BlockKind.TABLE)
    assert "| Years" in table.text
    assert doc.parser.startswith("docling ")


def test_html(parser: DoclingParser) -> None:
    html = (
        "<html><body><h1>Expenses</h1><h2>3. Travel</h2><p>3.1 Economy class only.</p>"
        "<ul><li>Receipts required</li></ul><table><tr><th>Item</th><th>Limit</th></tr>"
        "<tr><td>Hotel</td><td>150</td></tr></table></body></html>"
    )
    doc = parser.parse(html.encode(), MIME_HTML, "e.html")
    kinds = {b.kind for b in doc.blocks}
    assert {BlockKind.HEADING, BlockKind.PARAGRAPH, BlockKind.LIST_ITEM, BlockKind.TABLE} <= kinds


def test_docx(parser: DoclingParser) -> None:
    docx = pytest.importorskip("docx")  # python-docx ships with docling
    d = docx.Document()
    d.add_heading("Notice periods", 1)
    d.add_paragraph("5.1 Four weeks to the 15th or the end of a month.")
    buffer = io.BytesIO()
    d.save(buffer)
    doc = parser.parse(buffer.getvalue(), MIME_DOCX, "n.docx")
    texts = [b.text for b in doc.blocks]
    assert "Notice periods" in texts
    assert any(t.startswith("5.1 Four weeks") for t in texts)


def test_garbage_pdf_is_a_parse_error(parser: DoclingParser) -> None:
    with pytest.raises(ParseError):
        parser.parse(b"%PDF-1.7\nnot really a pdf", MIME_PDF, "broken.pdf")


@pytest.mark.docling_models
@pytest.mark.skipif(os.environ.get("DOCLING_MODELS") != "1", reason="needs Docling models")
def test_scanned_pdf_is_ocrd(parser: DoclingParser) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    draw.text((100, 150), "Sick Pay Policy", fill="black", font=font)
    draw.text((100, 260), "Employees receive full pay for six weeks.", fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")  # an image-only PDF: no text layer
    doc = parser.parse(buffer.getvalue(), MIME_PDF, "scan.pdf")
    text = " ".join(b.text for b in doc.blocks).lower()
    assert "six weeks" in text
    assert doc.ocr_confidence, "OCR confidence must be reported for scanned pages"
