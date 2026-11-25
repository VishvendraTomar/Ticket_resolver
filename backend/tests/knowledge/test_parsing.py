"""docs/failure-modes/parsing.md #3–#5, #11 — through the real task path (fake parser)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.providers.parser.fake import FakeParser
from tests.conftest import World
from tests.knowledge.helpers import get_version, upload

pytestmark = pytest.mark.db


async def _version_with(
    client: AsyncClient,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    parser: FakeParser,
    md: str | None = None,
) -> dict[str, object]:
    monkeypatch.setattr("workers.tasks.get_parser", lambda: parser)
    doc = await upload(client, world.bob, world.ws_b, md)
    return await get_version(client, world.bob, world.ws_b, doc["versions"][0]["id"])


async def test_low_ocr_confidence_flags_review(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = await _version_with(
        client, world, monkeypatch, FakeParser(ocr_confidence={1: 0.95, 2: 0.41, 3: 0.66})
    )
    assert version["pipeline_status"] == "awaiting_review"
    assert version["needs_review"] is True
    ocr = version["parse_report"]["ocr"]  # type: ignore[index]
    assert ocr["low_confidence_pages"] == [2, 3]
    assert ocr["min_confidence"] == 0.41


async def test_empty_parse_fails_with_reason(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = await _version_with(client, world, monkeypatch, FakeParser(), md="# Title\n\n")
    assert version["pipeline_status"] == "failed"
    assert "No text extracted" in str(version["pipeline_error"])


async def test_page_limit_fails_version(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = await _version_with(client, world, monkeypatch, FakeParser(page_count=10_000))
    assert version["pipeline_status"] == "failed"
    assert "over the 300-page limit" in str(version["pipeline_error"])


async def test_parse_report_records_parser(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = await _version_with(client, world, monkeypatch, FakeParser())
    assert version["parse_report"]["parser"] == "fake-markdown 1"  # type: ignore[index]
