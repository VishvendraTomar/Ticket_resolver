"""Storage and parser fakes/implementations that don't need external services."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.parser.base import BlockKind, ParseError
from app.providers.parser.fake import FakeParser, parse_markdown
from app.providers.storage.base import ObjectNotFound, validate_key
from app.providers.storage.local import LocalStorage
from app.providers.storage.memory import MemoryStorage


@pytest.mark.parametrize(
    "key", ["../etc/passwd", "a/../../b", "/abs", "a//b", "", "a b", "workspaces/x/../y"]
)
def test_storage_rejects_unsafe_keys(key: str) -> None:
    with pytest.raises(ValueError, match="invalid storage key"):
        validate_key(key)


@pytest.mark.parametrize("make", [lambda p: MemoryStorage(), lambda p: LocalStorage(p)])
async def test_storage_round_trip(tmp_path: Path, make: object) -> None:
    storage = make(tmp_path)  # type: ignore[operator]
    key = "workspaces/abc/originals/deadbeef.pdf"
    await storage.put(key, b"%PDF-1.7 data", "application/pdf")
    assert await storage.get(key) == b"%PDF-1.7 data"
    await storage.delete(key)
    with pytest.raises(ObjectNotFound):
        await storage.get(key)
    await storage.delete(key)  # idempotent


def test_fake_parser_reads_structure() -> None:
    blocks = parse_markdown(
        "# Handbook\n\n## 4. Leave\n\n4.1 Thirty days.\nMore text.\n\n| a | b |\n|---|---|\n"
        "| 1 | 2 |\n\n- item one\n"
    )
    assert [(b.kind, b.level) for b in blocks] == [
        (BlockKind.HEADING, 0),
        (BlockKind.HEADING, 1),
        (BlockKind.PARAGRAPH, None),
        (BlockKind.TABLE, None),
        (BlockKind.LIST_ITEM, None),
    ]
    assert blocks[2].text == "4.1 Thirty days. More text."
    assert blocks[3].text.count("\n") == 2


def test_fake_parser_can_fail() -> None:
    with pytest.raises(ParseError, match="encrypted"):
        FakeParser(fail_with="encrypted PDF").parse(b"x", "application/pdf", "a.pdf")
