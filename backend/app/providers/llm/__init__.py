"""LLM provider selection."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import LLMProvider, get_settings
from app.providers.llm.base import LLM


@lru_cache
def get_llm() -> LLM:
    settings = get_settings()
    if settings.llm_provider is LLMProvider.FAKE:
        from app.providers.llm.fake import FakeLLM

        return FakeLLM()
    from app.providers.llm.vertex import VertexLLM

    assert settings.vertex_project  # enforced by settings validation
    return VertexLLM(
        small_model=settings.llm_small_model,
        project=settings.vertex_project,
        location=settings.llm_location,
        timeout=settings.llm_timeout_seconds,
    )
