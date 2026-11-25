"""Auth provider selection."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import AuthProvider, get_settings
from app.providers.auth.base import AuthVerifier


@lru_cache
def get_auth_verifier() -> AuthVerifier:
    settings = get_settings()
    if settings.auth_provider is AuthProvider.FAKE:
        from app.providers.auth.fake import FakeAuthVerifier

        return FakeAuthVerifier()

    from app.providers.auth.clerk import ClerkAuthVerifier

    if not settings.clerk_issuer:
        raise RuntimeError("CLERK_ISSUER is required when AUTH_PROVIDER=clerk")
    return ClerkAuthVerifier(
        issuer=settings.clerk_issuer, authorized_parties=settings.authorized_parties
    )
