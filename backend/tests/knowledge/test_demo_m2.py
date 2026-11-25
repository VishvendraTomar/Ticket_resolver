"""seed/demo_m2.py must keep working: it is M2's end-to-end demo (real Docling parser)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.providers.parser.docling import DoclingParser

DEMO = Path(__file__).resolve().parents[3] / "seed" / "demo_m2.py"

pytestmark = pytest.mark.db


async def test_demo_m2_ingests_the_northwind_corpus(
    app_engine: AsyncEngine, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Markdown and HTML go through Docling's non-ML backends: fast, offline.
    docling = DoclingParser(max_pages=300, timeout_seconds=120)
    monkeypatch.setattr("workers.tasks.get_parser", lambda: docling)
    spec = importlib.util.spec_from_file_location("demo_m2", DEMO)
    assert spec is not None
    assert spec.loader is not None
    demo = importlib.util.module_from_spec(spec)
    sys.modules["demo_m2"] = demo
    spec.loader.exec_module(demo)

    assert await demo.run(None) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "[FAIL]" not in out
    assert out.count("[PASS]") == 9
