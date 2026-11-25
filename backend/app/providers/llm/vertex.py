"""Gemini on Vertex AI via LiteLLM, EU location only (ADR-0006)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.providers.llm.base import LLMError, LLMUnavailable, StructuredResult, T, Tier


class VertexLLM:
    def __init__(self, *, small_model: str, project: str, location: str, timeout: float) -> None:
        self.models = {Tier.SMALL: small_model}
        self.project = project
        self.location = location
        self.timeout = timeout

    async def structured(
        self, *, system: str, user: str, schema: type[T], tier: Tier = Tier.SMALL
    ) -> StructuredResult[T]:
        import litellm
        from litellm.exceptions import (
            APIConnectionError,
            APIError,
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )

        model = self.models[tier]
        try:
            response: Any = await litellm.acompletion(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format=schema,
                temperature=0,
                vertex_project=self.project,
                vertex_location=self.location,
                timeout=self.timeout,
                num_retries=2,
            )
        except (
            RateLimitError,
            Timeout,
            APIConnectionError,
            ServiceUnavailableError,
            InternalServerError,
        ) as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
        except APIError as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        content = response.choices[0].message.content or ""
        try:
            value = schema.model_validate_json(content)
        except ValidationError as exc:
            raise LLMError(f"output does not match {schema.__name__}: {exc}") from exc
        hidden = getattr(response, "_hidden_params", None) or {}
        cost = hidden.get("response_cost")
        return StructuredResult(value=value, model=str(response.model or model), cost_usd=cost)
