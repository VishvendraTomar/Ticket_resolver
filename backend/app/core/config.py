"""Application settings, read from environment variables (and the repo-root .env).

Every variable here must also appear in /.env.example.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class AuthProvider(StrEnum):
    FAKE = "fake"
    CLERK = "clerk"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"

    # Owner role: migrations and catalog inspection only. Never used by the running app.
    database_url: SecretStr | None = None
    # app_user (NOBYPASSRLS): everything the running app does.
    app_database_url: SecretStr | None = None

    auth_provider: AuthProvider = AuthProvider.CLERK
    # Clerk: issuer is the Frontend API URL, e.g. https://<slug>.clerk.accounts.dev
    clerk_issuer: str | None = None
    # Comma-separated origins allowed in the `azp` claim, e.g. http://localhost:3000
    clerk_authorized_parties: str = ""

    sentry_dsn: SecretStr | None = None

    cors_origins: str = Field(default="http://localhost:3000")

    @model_validator(mode="after")
    def _guard_fake_auth(self) -> Settings:
        if self.auth_provider is AuthProvider.FAKE and self.environment not in (
            Environment.LOCAL,
            Environment.TEST,
        ):
            raise ValueError("AUTH_PROVIDER=fake is only allowed when ENVIRONMENT is local or test")
        if (
            self.auth_provider is AuthProvider.CLERK
            and self.environment
            in (
                Environment.STAGING,
                Environment.PRODUCTION,
            )
            and not self.clerk_issuer
        ):
            raise ValueError("CLERK_ISSUER is required when AUTH_PROVIDER=clerk")
        return self

    @property
    def authorized_parties(self) -> list[str]:
        return [p.strip() for p in self.clerk_authorized_parties.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


@dataclass(frozen=True)
class AsyncpgUrl:
    """A libpq-style URL translated for SQLAlchemy + asyncpg."""

    url: str
    connect_args: dict[str, Any]


_SSL_MODES_REQUIRING_TLS = {"require", "verify-ca", "verify-full"}
_LIBPQ_ONLY_PARAMS = {"sslmode", "channel_binding"}


def to_asyncpg_url(raw: str) -> AsyncpgUrl:
    """Translate a URL as Neon/libpq gives it into what asyncpg accepts.

    Neon hands out ``postgresql://u:p@host/db?sslmode=require&channel_binding=require``.
    asyncpg rejects ``sslmode``/``channel_binding`` as query params; TLS is passed
    through ``connect_args`` instead.
    """
    parts = urlsplit(raw)
    if parts.scheme not in ("postgres", "postgresql", "postgresql+asyncpg"):
        raise ValueError(f"Unsupported database URL scheme: {parts.scheme!r}")

    query = dict(parse_qsl(parts.query))
    sslmode = query.get("sslmode")
    kept = {k: v for k, v in query.items() if k not in _LIBPQ_ONLY_PARAMS}

    connect_args: dict[str, Any] = {}
    if sslmode in _SSL_MODES_REQUIRING_TLS:
        connect_args["ssl"] = "require" if sslmode == "require" else sslmode
    elif sslmode is None and parts.hostname and parts.hostname.endswith(".neon.tech"):
        # Neon always requires TLS; don't silently connect without it.
        connect_args["ssl"] = "require"

    url = urlunsplit(
        ("postgresql+asyncpg", parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )
    return AsyncpgUrl(url=url, connect_args=connect_args)
