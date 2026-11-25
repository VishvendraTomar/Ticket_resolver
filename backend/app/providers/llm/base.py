"""LLM interface (ADR-0004, ADR-0006). All real calls go through LiteLLM.

M2 needs one operation: structured output against a Pydantic schema, from the
small model. The strong model and plain completion arrive in M4.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class Tier(StrEnum):
    SMALL = "small"


class LLMError(Exception):
    """Permanent failure, or output that doesn't match the schema."""


class LLMUnavailable(LLMError):
    """Transient failure (rate limit, timeout, 5xx)."""


@dataclass(frozen=True)
class StructuredResult[M: BaseModel]:
    value: M
    model: str  # the provider's model id, recorded for audit
    cost_usd: float | None = None


class LLM(Protocol):
    async def structured(
        self, *, system: str, user: str, schema: type[T], tier: Tier = Tier.SMALL
    ) -> StructuredResult[T]: ...
