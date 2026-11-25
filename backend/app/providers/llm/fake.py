"""Scripted LLM for tests and offline dev.

By default it returns the schema's defaults (an empty answer), which is a valid
"no suggestion". Tests pass a responder to script outputs, or `fail_with` to
simulate outages.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.providers.llm.base import LLMError, StructuredResult, T, Tier

Responder = Callable[[str, str, type[Any]], dict[str, Any] | str]


class FakeLLM:
    def __init__(
        self, responder: Responder | None = None, fail_with: Exception | None = None
    ) -> None:
        self.responder = responder
        self.fail_with = fail_with
        self.calls: list[tuple[str, str]] = []

    async def structured(
        self, *, system: str, user: str, schema: type[T], tier: Tier = Tier.SMALL
    ) -> StructuredResult[T]:
        self.calls.append((system, user))
        if self.fail_with:
            raise self.fail_with
        raw = self.responder(system, user, schema) if self.responder else {}
        try:
            if isinstance(raw, str):
                value = schema.model_validate_json(raw)
            else:
                value = schema.model_validate(raw)
        except ValueError as exc:
            raise LLMError(f"output does not match {schema.__name__}: {exc}") from exc
        return StructuredResult(value=value, model="fake/scripted", cost_usd=0.0)
