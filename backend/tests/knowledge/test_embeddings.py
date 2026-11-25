"""docs/failure-modes/embeddings.md — provider-level cases (DB cases are further down)."""

from __future__ import annotations

import math

import pytest

from app.providers.embeddings.base import EmbeddingError, EmbeddingUnavailable, InputType
from app.providers.embeddings.fake import FakeRawEmbedder
from app.providers.embeddings.validating import ValidatingEmbedder


class StubRaw:
    model_key = "stub/model@4"
    dims = 4

    def __init__(self, vectors: list[list[float]] | None = None, fail_times: int = 0) -> None:
        self.vectors = vectors or [[3.0, 4.0, 0.0, 0.0]]
        self.fail_times = fail_times
        self.calls = 0

    async def embed_one(self, text: str, input_type: InputType) -> list[float]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise EmbeddingUnavailable("429 rate limited")
        return self.vectors[0]


async def _no_sleep(_: float) -> None:
    return None


def wrap(raw: StubRaw | FakeRawEmbedder, **kw: object) -> ValidatingEmbedder:
    return ValidatingEmbedder(raw, max_tokens=100, sleep=_no_sleep, **kw)  # type: ignore[arg-type]


async def test_wrong_dimension_is_rejected() -> None:
    raw = StubRaw(vectors=[[0.1] * 3072])
    with pytest.raises(EmbeddingError, match="3072 dimensions, expected 4"):
        await wrap(raw).embed(["annual leave"], InputType.DOCUMENT)


async def test_non_finite_and_zero_vectors_are_rejected() -> None:
    with pytest.raises(EmbeddingError, match="non-finite"):
        await wrap(StubRaw(vectors=[[math.nan, 1, 1, 1]])).embed(["x"], InputType.DOCUMENT)
    with pytest.raises(EmbeddingError, match="zero vector"):
        await wrap(StubRaw(vectors=[[0, 0, 0, 0]])).embed(["x"], InputType.DOCUMENT)


async def test_vectors_are_l2_normalised() -> None:
    [vector] = await wrap(StubRaw()).embed(["x"], InputType.DOCUMENT)
    assert vector == pytest.approx([0.6, 0.8, 0.0, 0.0])
    fake_vectors = await wrap(FakeRawEmbedder(768)).embed(
        ["Employees get 30 days of annual leave.", "Sick pay for six weeks."], InputType.DOCUMENT
    )
    for v in fake_vectors:
        assert math.sqrt(sum(x * x for x in v)) == pytest.approx(1.0)


async def test_transient_errors_are_retried() -> None:
    raw = StubRaw(fail_times=2)
    [vector] = await wrap(raw).embed(["x"], InputType.DOCUMENT)
    assert raw.calls == 3
    assert vector == pytest.approx([0.6, 0.8, 0.0, 0.0])

    always_down = StubRaw(fail_times=99)
    with pytest.raises(EmbeddingUnavailable):
        await wrap(always_down, max_attempts=4).embed(["x"], InputType.DOCUMENT)
    assert always_down.calls == 4


async def test_overlong_input_is_rejected() -> None:
    raw = StubRaw()
    with pytest.raises(EmbeddingError, match="over the 100-token budget"):
        await wrap(raw).embed(["word " * 200], InputType.DOCUMENT)
    assert raw.calls == 0  # nothing was sent, so nothing was silently truncated


async def test_input_type_reaches_provider() -> None:
    raw = FakeRawEmbedder(16)
    embedder = wrap(raw)
    await embedder.embed(["chunk text"], InputType.DOCUMENT)
    await embedder.embed(["how many leave days?"], InputType.QUERY)
    assert [t for _, t in raw.calls] == [InputType.DOCUMENT, InputType.QUERY]


async def test_fake_embedder_is_deterministic_and_meaningful() -> None:
    embedder = wrap(FakeRawEmbedder(256))
    a1, a2, b = await embedder.embed(
        ["annual leave days per year", "annual leave days per year", "expense receipts for travel"],
        InputType.DOCUMENT,
    )
    assert a1 == a2
    [q] = await embedder.embed(["how many annual leave days"], InputType.QUERY)

    def dot(x: list[float], y: list[float]) -> float:
        return sum(i * j for i, j in zip(x, y, strict=True))

    assert dot(q, a1) > dot(q, b)
