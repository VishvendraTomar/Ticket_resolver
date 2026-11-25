"""Fake verifier for tests and local development.

Token format: ``fake|<subject>|<email>|<name>`` (email and name may be empty).
Settings refuse to start with this verifier outside ENVIRONMENT=local/test.
"""

from __future__ import annotations

from app.providers.auth.base import InvalidToken, Principal

PREFIX = "fake|"


def make_fake_token(subject: str, email: str | None = None, name: str | None = None) -> str:
    if "|" in subject or "|" in (email or "") or "|" in (name or ""):
        raise ValueError("fake token fields must not contain '|'")
    return f"{PREFIX}{subject}|{email or ''}|{name or ''}"


class FakeAuthVerifier:
    async def verify(self, token: str) -> Principal:
        if not token.startswith(PREFIX):
            raise InvalidToken("not a fake token")
        parts = token[len(PREFIX) :].split("|")
        if len(parts) != 3 or not parts[0]:
            raise InvalidToken("malformed fake token")
        subject, email, name = parts
        return Principal(subject=subject, email=email or None, name=name or None)
