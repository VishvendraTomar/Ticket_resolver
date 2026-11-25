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


class StorageProvider(StrEnum):
    MEMORY = "memory"  # tests
    LOCAL = "local"  # dev: files under STORAGE_LOCAL_DIR
    GCS = "gcs"  # Cloud Storage (or fake-gcs-server via STORAGE_EMULATOR_HOST)


class ParserProvider(StrEnum):
    FAKE = "fake"
    DOCLING = "docling"


class EmbeddingsProvider(StrEnum):
    FAKE = "fake"
    VERTEX = "vertex"


class LLMProvider(StrEnum):
    FAKE = "fake"
    VERTEX = "vertex"


# Vertex AI locations whose ML processing stays in the EU (ADR-0006). "global" never.
def is_eu_vertex_location(location: str) -> bool:
    return location == "eu" or location.startswith("europe-")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # `FOO=` in .env means "use the default"
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

    # --- Jobs (ADR-0007) ---------------------------------------------------------------
    celery_broker_url: str = "redis://localhost:6379/0"
    # Run tasks inline (tests, and local dev without a worker).
    celery_task_always_eager: bool = False

    # --- Storage ---------------------------------------------------------------------
    storage_provider: StorageProvider = StorageProvider.LOCAL
    storage_local_dir: Path = REPO_ROOT / "data" / "uploads"
    gcs_bucket: str | None = None

    # --- Uploads and parsing (docs/failure-modes/parsing.md) -----------------------------
    parser_provider: ParserProvider = ParserProvider.DOCLING
    max_upload_mb: int = 50
    max_pages: int = 300
    parse_timeout_seconds: int = 900
    ocr_min_confidence: float = 0.7

    # --- Vertex AI (ADR-0006). Credentials come from ADC, never from this file. --------
    vertex_project: str | None = None

    embeddings_provider: EmbeddingsProvider = EmbeddingsProvider.FAKE
    embeddings_model: str = "gemini-embedding-001"
    embeddings_dims: int = 768
    embeddings_location: str = "europe-west4"
    embeddings_concurrency: int = 8
    # Header + chunk must stay well under the model's 2,048-token input limit.
    embed_max_tokens: int = 1800

    llm_provider: LLMProvider = LLMProvider.FAKE
    llm_small_model: str = "vertex_ai/gemini-3.5-flash"
    llm_location: str = "europe-west3"
    llm_timeout_seconds: int = 60
    tagging_max_sections: int = 200

    @model_validator(mode="after")
    def _guard_fake_auth(self) -> Settings:
        if self.auth_provider is AuthProvider.FAKE and self.environment not in (
            Environment.LOCAL,
            Environment.TEST,
        ):
            raise ValueError("AUTH_PROVIDER=fake is only allowed when ENVIRONMENT is local or test")
        if self.auth_provider is AuthProvider.CLERK and self.environment not in (
            Environment.LOCAL,
            Environment.TEST,
        ):
            if not self.clerk_issuer:
                raise ValueError("CLERK_ISSUER is required when AUTH_PROVIDER=clerk")
            # An empty list would switch the azp check off (ADR-0003).
            if not self.authorized_parties:
                raise ValueError(
                    "CLERK_AUTHORIZED_PARTIES is required when AUTH_PROVIDER=clerk "
                    "outside local/test"
                )
        return self

    @model_validator(mode="after")
    def _guard_providers(self) -> Settings:
        """Fakes only in local/test (ADR-0004); Vertex only in the EU (ADR-0006)."""
        if self.environment not in (Environment.LOCAL, Environment.TEST):
            fakes = [
                name
                for name, is_fake in (
                    ("EMBEDDINGS_PROVIDER", self.embeddings_provider is EmbeddingsProvider.FAKE),
                    ("LLM_PROVIDER", self.llm_provider is LLMProvider.FAKE),
                    ("PARSER_PROVIDER", self.parser_provider is ParserProvider.FAKE),
                    ("STORAGE_PROVIDER", self.storage_provider is not StorageProvider.GCS),
                )
                if is_fake
            ]
            if fakes:
                raise ValueError(
                    f"{', '.join(fakes)}: fake/local providers are only allowed when "
                    "ENVIRONMENT is local or test"
                )
            if self.celery_task_always_eager:
                raise ValueError("CELERY_TASK_ALWAYS_EAGER is only for local/test")
        for name, provider, location in (
            ("EMBEDDINGS_LOCATION", self.embeddings_provider, self.embeddings_location),
            ("LLM_LOCATION", self.llm_provider, self.llm_location),
        ):
            uses_vertex = provider in (EmbeddingsProvider.VERTEX, LLMProvider.VERTEX)
            if uses_vertex and not is_eu_vertex_location(location):
                raise ValueError(f"{name}={location!r}: Vertex AI must run in an EU location")
            if uses_vertex and not self.vertex_project:
                raise ValueError("VERTEX_PROJECT is required for Vertex AI providers")
        if self.storage_provider is StorageProvider.GCS and not self.gcs_bucket:
            raise ValueError("GCS_BUCKET is required when STORAGE_PROVIDER=gcs")
        return self

    @property
    def embedding_model_key(self) -> str:
        """Provider, model and size, e.g. vertex/gemini-embedding-001@768."""
        if self.embeddings_provider is EmbeddingsProvider.FAKE:
            return f"fake/hash@{self.embeddings_dims}"
        return f"vertex/{self.embeddings_model}@{self.embeddings_dims}"

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
