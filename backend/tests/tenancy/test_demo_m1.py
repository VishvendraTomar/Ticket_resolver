"""seed/demo_m1.py must keep working: it is M1's end-to-end isolation demo."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

DEMO = Path(__file__).resolve().parents[3] / "seed" / "demo_m1.py"

pytestmark = pytest.mark.db


async def test_demo_m1_runs_and_every_isolation_check_passes(
    app_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = importlib.util.spec_from_file_location("demo_m1", DEMO)
    assert spec is not None
    assert spec.loader is not None
    demo = importlib.util.module_from_spec(spec)
    sys.modules["demo_m1"] = demo  # dataclasses look their module up while executing
    spec.loader.exec_module(demo)

    assert await demo.run(None) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "[FAIL]" not in out
    assert out.count("[PASS]") >= 15
