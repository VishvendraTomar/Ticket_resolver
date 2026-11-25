"""Docling parser (ADR-0006). Runs in the ingestion worker, never in the API.

Markdown, HTML and DOCX use Docling's non-ML backends. PDF uses the layout model,
table structure and OCR (RapidOCR); models are downloaded once into the worker's
cache. Per-page OCR confidence comes from Docling's confidence report.
"""

from __future__ import annotations

import io
import math
from functools import cached_property
from importlib.metadata import version

from app.providers.parser.base import (
    MIME_DOCX,
    MIME_HTML,
    MIME_MARKDOWN,
    MIME_PDF,
    Block,
    BlockKind,
    ParsedDocument,
    ParseError,
)


class DoclingParser:
    def __init__(self, *, max_pages: int, timeout_seconds: int) -> None:
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.name = f"docling {version('docling')}"

    @cached_property
    def _converter(self):  # type: ignore[no-untyped-def]  # docling is untyped
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pdf = PdfPipelineOptions(
            do_ocr=True,
            ocr_options=RapidOcrOptions(),
            do_table_structure=True,
            document_timeout=float(self.timeout_seconds),
        )
        return DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.HTML, InputFormat.MD],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf)},
        )

    def parse(self, data: bytes, mime_type: str, file_name: str) -> ParsedDocument:
        from docling.datamodel.base_models import ConversionStatus
        from docling_core.types.doc.items.table.table import TableItem
        from docling_core.types.doc.items.text import (
            ListItem,
            SectionHeaderItem,
            TextItem,
            TitleItem,
        )
        from docling_core.types.io import DocumentStream

        suffix = {MIME_PDF: ".pdf", MIME_DOCX: ".docx", MIME_HTML: ".html", MIME_MARKDOWN: ".md"}
        if mime_type not in suffix:
            raise ParseError(f"unsupported file type: {mime_type}")
        stream = DocumentStream(name=f"upload{suffix[mime_type]}", stream=io.BytesIO(data))
        try:
            result = self._converter.convert(
                stream, raises_on_error=False, max_num_pages=self.max_pages
            )
        except Exception as exc:  # docling raises many types; editors get the message
            raise ParseError(f"parser error: {exc}") from exc
        if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
            reasons = "; ".join(str(e.error_message) for e in result.errors) or str(result.status)
            raise ParseError(f"could not parse document: {reasons}")

        doc = result.document
        blocks: list[Block] = []
        for item, _depth in doc.iterate_items():
            page = item.prov[0].page_no if getattr(item, "prov", None) else None
            if isinstance(item, TitleItem):
                blocks.append(Block(BlockKind.HEADING, item.text.strip(), level=0, page=page))
            elif isinstance(item, SectionHeaderItem):
                level = item.level
                blocks.append(Block(BlockKind.HEADING, item.text.strip(), level=level, page=page))
            elif isinstance(item, TableItem):
                blocks.append(Block(BlockKind.TABLE, item.export_to_markdown(doc), page=page))
            elif isinstance(item, ListItem):
                blocks.append(Block(BlockKind.LIST_ITEM, item.text.strip(), page=page))
            elif isinstance(item, TextItem) and item.text.strip():
                blocks.append(Block(BlockKind.PARAGRAPH, item.text.strip(), page=page))

        ocr: dict[int, float] = {}
        for page_no, scores in (result.confidence.pages or {}).items():
            score = scores.ocr_score
            if score is not None and not math.isnan(score):
                ocr[int(page_no)] = float(score)
        warnings = [str(e.error_message) for e in result.errors]
        if result.status == ConversionStatus.PARTIAL_SUCCESS:
            warnings.append("partial parse: some pages failed (see errors)")
        return ParsedDocument(
            blocks=blocks,
            parser=self.name,
            page_count=len(result.pages) if result.pages else None,
            ocr_confidence=ocr,
            warnings=warnings,
        )
