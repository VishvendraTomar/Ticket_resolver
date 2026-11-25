"""Clerk session-token verification (identity only — see ADR-0003).

Clerk issues short-lived RS256 JWTs. We verify signature (JWKS), issuer, expiry,
not-before and the ``azp`` (authorised party) claim. Workspaces and roles are
ours; Clerk organisations are not used.

``email`` and ``name`` are read from custom session-token claims, configured in
the Clerk dashboard (Sessions → Customize session token):
    {"email": "{{user.primary_email_address}}", "name": "{{user.full_name}}"}
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import jwt

from app.providers.auth.base import InvalidToken, Principal


class SigningKeySource(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


class ClerkAuthVerifier:
    def __init__(
        self,
        issuer: str,
        authorized_parties: list[str],
        *,
        key_source: SigningKeySource | None = None,
        leeway_seconds: int = 5,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._authorized_parties = set(authorized_parties)
        self._keys: SigningKeySource = key_source or jwt.PyJWKClient(
            f"{self._issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600
        )
        self._leeway = leeway_seconds

    async def verify(self, token: str) -> Principal:
        try:
            # PyJWKClient fetches over blocking HTTP on a cache miss; keep it off the loop.
            signing_key = await asyncio.to_thread(self._keys.get_signing_key_from_jwt, token)
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "sub"], "verify_aud": False},
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise InvalidToken(str(exc)) from exc

        if self._authorized_parties:
            azp = claims.get("azp")
            if azp not in self._authorized_parties:
                raise InvalidToken(f"azp {azp!r} is not an authorised party")

        email = claims.get("email")
        name = claims.get("name")
        return Principal(
            subject=str(claims["sub"]),
            email=email if isinstance(email, str) and email else None,
            name=name if isinstance(name, str) and name else None,
        )
