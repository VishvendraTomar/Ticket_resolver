"""Parser provider selection."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import ParserProvider, get_settings
from app.providers.parser.base import Parser


@lru_cache
def get_parser() -> Parser:
    settings = get_settings()
    if settings.parser_provider is ParserProvider.FAKE:
        from app.providers.parser.fake import FakeParser

        return FakeParser()
    from app.providers.parser.docling import DoclingParser

    return DoclingParser(
        max_pages=settings.max_pages, timeout_seconds=settings.parse_timeout_seconds
    )
