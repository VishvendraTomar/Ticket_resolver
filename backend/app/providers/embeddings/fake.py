"""Deterministic offline embedder (hashing trick over lowercased words).

Texts that share words get similar vectors, so retrieval code can be tested
meaningfully offline. Records every call for assertions.
"""

from __future__ import annotations

import hashlib
import re

from app.providers.embeddings.base import InputType

_WORD = re.compile(r"\w+", re.UNICODE)


class FakeRawEmbedder:
    def __init__(self, dims: int) -> None:
        self.dims = dims
        self.model_key = f"fake/hash@{dims}"
        self.calls: list[tuple[str, InputType]] = []

    async def embed_one(self, text: str, input_type: InputType) -> list[float]:
        self.calls.append((text, input_type))
        vector = [0.0] * self.dims
        for word in _WORD.findall(text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dims
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        if not any(vector):
            vector[0] = 1.0
        return vector
