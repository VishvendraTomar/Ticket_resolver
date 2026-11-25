"""Identity verification interface. Implementations: fake (tests/local), clerk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Principal:
    """A verified identity. Authorisation (workspaces, roles) is ours, not the provider's."""

    subject: str
    email: str | None
    name: str | None


class InvalidToken(Exception):
    """The bearer token is missing, malformed, expired or not trusted."""


class AuthVerifier(Protocol):
    async def verify(self, token: str) -> Principal: ...
