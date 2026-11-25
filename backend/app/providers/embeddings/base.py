"""Embeddings interface (ADR-0004, ADR-0006, docs/failure-modes/embeddings.md).

Vendors implement `RawEmbedder` (one text in, one vector out). The app always
gets a `ValidatingEmbedder` around it, which enforces the token budget,
retries transient errors, checks dimensions and L2-normalises.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol


class InputType(StrEnum):
    DOCUMENT = "document"  # chunks being indexed (RETRIEVAL_DOCUMENT)
    QUERY = "query"  # search queries, M3 (RETRIEVAL_QUERY)


class EmbeddingError(Exception):
    """Permanent failure: retrying the same input won't help."""


class EmbeddingUnavailable(EmbeddingError):
    """Transient failure (rate limit, timeout, 5xx): safe to retry."""


class RawEmbedder(Protocol):
    model_key: str  # provider/model@dims, stored on every embedding row
    dims: int

    async def embed_one(self, text: str, input_type: InputType) -> list[float]: ...


class Embedder(Protocol):
    model_key: str
    dims: int

    async def embed(self, texts: Sequence[str], input_type: InputType) -> list[list[float]]: ...
