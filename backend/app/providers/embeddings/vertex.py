"""Vertex AI gemini-embedding-001 via LiteLLM (ADR-0006).

One text per request (a Vertex limit for this model); the ValidatingEmbedder
runs requests concurrently with a bound. EU location only (settings enforce it).
"""

from __future__ import annotations

from typing import Any

from app.providers.embeddings.base import EmbeddingError, EmbeddingUnavailable, InputType

_TASK_TYPE = {InputType.DOCUMENT: "RETRIEVAL_DOCUMENT", InputType.QUERY: "RETRIEVAL_QUERY"}


class VertexRawEmbedder:
    def __init__(
        self, *, model: str, dims: int, project: str, location: str, timeout: float = 30.0
    ) -> None:
        self.model = model
        self.dims = dims
        self.model_key = f"vertex/{model}@{dims}"
        self.project = project
        self.location = location
        self.timeout = timeout

    async def embed_one(self, text: str, input_type: InputType) -> list[float]:
        import litellm
        from litellm.exceptions import (
            APIConnectionError,
            APIError,
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )

        try:
            response: Any = await litellm.aembedding(
                model=f"vertex_ai/{self.model}",
                input=[text],
                dimensions=self.dims,
                input_type=_TASK_TYPE[input_type],
                vertex_project=self.project,
                vertex_location=self.location,
                timeout=self.timeout,
            )
        except (
            RateLimitError,
            Timeout,
            APIConnectionError,
            ServiceUnavailableError,
            InternalServerError,
        ) as exc:
            raise EmbeddingUnavailable(f"{type(exc).__name__}: {exc}") from exc
        except APIError as exc:
            raise EmbeddingError(f"{type(exc).__name__}: {exc}") from exc
        data = response.data[0]
        embedding = data["embedding"] if isinstance(data, dict) else data.embedding
        return [float(x) for x in embedding]
