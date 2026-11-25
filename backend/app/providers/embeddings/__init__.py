"""Embeddings provider selection. Always returns a ValidatingEmbedder."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import EmbeddingsProvider, get_settings
from app.providers.embeddings.base import Embedder, RawEmbedder
from app.providers.embeddings.validating import ValidatingEmbedder


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    raw: RawEmbedder
    if settings.embeddings_provider is EmbeddingsProvider.FAKE:
        from app.providers.embeddings.fake import FakeRawEmbedder

        raw = FakeRawEmbedder(settings.embeddings_dims)
    else:
        from app.providers.embeddings.vertex import VertexRawEmbedder

        assert settings.vertex_project  # enforced by settings validation
        raw = VertexRawEmbedder(
            model=settings.embeddings_model,
            dims=settings.embeddings_dims,
            project=settings.vertex_project,
            location=settings.embeddings_location,
        )
    return ValidatingEmbedder(
        raw, max_tokens=settings.embed_max_tokens, concurrency=settings.embeddings_concurrency
    )
