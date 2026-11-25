"""The wrapper every embedder goes through (docs/failure-modes/embeddings.md)."""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable, Sequence

from app.core.tokens import estimate_tokens
from app.providers.embeddings.base import (
    EmbeddingError,
    EmbeddingUnavailable,
    InputType,
    RawEmbedder,
)


class ValidatingEmbedder:
    def __init__(
        self,
        raw: RawEmbedder,
        *,
        max_tokens: int,
        concurrency: int = 8,
        max_attempts: int = 5,
        base_delay: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.raw = raw
        self.model_key = raw.model_key
        self.dims = raw.dims
        self.max_tokens = max_tokens
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self._sleep = sleep
        self.concurrency = concurrency

    async def embed(self, texts: Sequence[str], input_type: InputType) -> list[list[float]]:
        for i, text in enumerate(texts):
            tokens = estimate_tokens(text)
            if not text.strip():
                raise EmbeddingError(f"input {i} is empty")
            if tokens > self.max_tokens:
                # Never let the provider silently truncate (failure mode #6).
                raise EmbeddingError(
                    f"input {i} is ~{tokens} tokens, over the {self.max_tokens}-token budget"
                )
        # Per call: a semaphore binds to one event loop, and tasks run in fresh loops.
        semaphore = asyncio.Semaphore(self.concurrency)
        return list(await asyncio.gather(*(self._one(t, input_type, semaphore) for t in texts)))

    async def _one(
        self, text: str, input_type: InputType, semaphore: asyncio.Semaphore
    ) -> list[float]:
        async with semaphore:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    vector = await self.raw.embed_one(text, input_type)
                    break
                except EmbeddingUnavailable:
                    if attempt == self.max_attempts:
                        raise
                    # Exponential backoff with full jitter.
                    delay = random.uniform(0, self.base_delay * 2 ** (attempt - 1))  # noqa: S311
                    await self._sleep(delay)
        return self._check(vector)

    def _check(self, vector: list[float]) -> list[float]:
        if len(vector) != self.dims:
            raise EmbeddingError(
                f"{self.model_key} returned {len(vector)} dimensions, expected {self.dims}"
            )
        if not all(math.isfinite(x) for x in vector):
            raise EmbeddingError(f"{self.model_key} returned a non-finite value")
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0:
            raise EmbeddingError(f"{self.model_key} returned a zero vector")
        return [x / norm for x in vector]  # only full-size Gemini vectors come normalised
