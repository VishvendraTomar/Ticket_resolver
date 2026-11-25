"""Live contract tests against Vertex AI (ADR-0004 rule 6, ADR-0006). Opt-in:

    RUN_LIVE=1 VERTEX_PROJECT=<project> uv run pytest tests/live -m live

Credentials come from Application Default Credentials. These check the same
contract the fakes are held to, on the real EU endpoints.
"""

from __future__ import annotations

import math
import os

import pytest

from app.core.config import get_settings
from app.ingestion.tagging import SectionInput, Vocabulary, suggest_tags
from app.providers.embeddings.base import InputType
from app.providers.embeddings.validating import ValidatingEmbedder
from app.providers.embeddings.vertex import VertexRawEmbedder
from app.providers.llm.vertex import VertexLLM

pytestmark = pytest.mark.live


def _project() -> str:
    project = os.environ.get("VERTEX_PROJECT") or get_settings().vertex_project
    if not project:
        pytest.skip("VERTEX_PROJECT is not set")
    return project


async def test_embeddings_contract_768_eu() -> None:
    settings = get_settings()
    raw = VertexRawEmbedder(
        model=settings.embeddings_model,
        dims=768,
        project=_project(),
        location=settings.embeddings_location,
    )
    embedder = ValidatingEmbedder(raw, max_tokens=settings.embed_max_tokens, concurrency=2)
    leave, pay, query = (
        *await embedder.embed(
            [
                "Employees receive 30 days of annual leave per year.",
                "Salaries are paid on the last working day of each month.",
            ],
            InputType.DOCUMENT,
        ),
        (await embedder.embed(["How many holiday days do I get?"], InputType.QUERY))[0],
    )
    for vector in (leave, pay, query):
        assert len(vector) == 768
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, rel_tol=1e-6)

    def dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert dot(query, leave) > dot(query, pay)


async def test_small_llm_tag_suggestions_eu() -> None:
    settings = get_settings()
    llm = VertexLLM(
        small_model=settings.llm_small_model,
        project=_project(),
        location=settings.llm_location,
        timeout=settings.llm_timeout_seconds,
    )
    out = await suggest_tags(
        llm,
        document_title="Northwind Germany Leave Policy",
        language="en",
        sections=[
            SectionInput(0, ["1. Annual leave"], "Employees in Germany receive 30 working days."),
            SectionInput(1, ["Annex BY"], "In Bavaria, Assumption Day is a public holiday."),
        ],
        vocab=Vocabulary(
            jurisdiction_codes=frozenset({"GLOBAL", "EU", "DE", "DE-BY", "FR"}),
            topics={"leave": "Annual leave", "public_holidays": "Public holidays"},
            scope_fields={},
        ),
        max_sections=10,
    )
    assert out["status"] == "ok", out
    assert out["version"].get("jurisdiction") in {"DE", "DE-BY"}
    assert out["models"]
