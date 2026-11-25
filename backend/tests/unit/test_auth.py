"""Auth verifiers, offline. The Clerk verifier is tested with a locally generated key."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.providers.auth.base import InvalidToken
from app.providers.auth.clerk import ClerkAuthVerifier
from app.providers.auth.fake import FakeAuthVerifier, make_fake_token

ISSUER = "https://example.clerk.accounts.dev"
ORIGIN = "http://localhost:3000"


# --- Fake ----------------------------------------------------------------------------


async def test_fake_round_trip() -> None:
    p = await FakeAuthVerifier().verify(make_fake_token("u1", "a@b.test", "Ann"))
    assert (p.subject, p.email, p.name) == ("u1", "a@b.test", "Ann")


@pytest.mark.parametrize("token", ["", "u1|a|b", "fake|", "fake||a|b", "fake|a|b"])
async def test_fake_rejects_malformed(token: str) -> None:
    with pytest.raises(InvalidToken):
        await FakeAuthVerifier().verify(token)


# --- Clerk ---------------------------------------------------------------------------


class _StaticKeys:
    def __init__(self, public_key: Any) -> None:
        self._jwk = jwt.PyJWK.from_dict(
            {**jwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True), "alg": "RS256"}
        )

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        return self._jwk


@pytest.fixture(scope="module")
def keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "user_123",
        "azp": ORIGIN,
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "email": "ann@example.test",
        "name": "Ann",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256")


def _verifier(key: rsa.RSAPrivateKey) -> ClerkAuthVerifier:
    return ClerkAuthVerifier(ISSUER, [ORIGIN], key_source=_StaticKeys(key.public_key()))


async def test_clerk_accepts_valid_token(keypair: rsa.RSAPrivateKey) -> None:
    p = await _verifier(keypair).verify(_token(keypair))
    assert (p.subject, p.email, p.name) == ("user_123", "ann@example.test", "Ann")


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 120},  # expired
        {"nbf": int(time.time()) + 120},  # not yet valid
        {"iss": "https://evil.example"},  # wrong issuer
        {"azp": "https://evil.example"},  # wrong authorised party
        {"azp": None},  # missing azp
        {"sub": None},  # missing subject
    ],
    ids=["expired", "nbf", "issuer", "azp", "no-azp", "no-sub"],
)
async def test_clerk_rejects_bad_claims(
    keypair: rsa.RSAPrivateKey, overrides: dict[str, Any]
) -> None:
    with pytest.raises(InvalidToken):
        await _verifier(keypair).verify(_token(keypair, **overrides))


async def test_clerk_rejects_wrong_signature(keypair: rsa.RSAPrivateKey) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(InvalidToken):
        await _verifier(keypair).verify(_token(other))


async def test_clerk_rejects_hs256_downgrade(keypair: rsa.RSAPrivateKey) -> None:
    forged = jwt.encode(
        {"iss": ISSUER, "sub": "x", "azp": ORIGIN, "iat": 0, "exp": 2**31},
        "secret",
        algorithm="HS256",
    )
    with pytest.raises(InvalidToken):
        await _verifier(keypair).verify(forged)
