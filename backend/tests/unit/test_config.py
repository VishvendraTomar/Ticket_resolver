from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import (
    AuthProvider,
    EmbeddingsProvider,
    Environment,
    LLMProvider,
    ParserProvider,
    Settings,
    StorageProvider,
    to_asyncpg_url,
)


def test_neon_url_is_translated_for_asyncpg() -> None:
    target = to_asyncpg_url(
        "postgresql://app_user:s3cr%40t@ep-x-123.eu-central-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    assert target.url == (
        "postgresql+asyncpg://app_user:s3cr%40t@ep-x-123.eu-central-1.aws.neon.tech/neondb"
    )
    assert target.connect_args == {"ssl": "require"}


def test_neon_without_sslmode_still_requires_tls() -> None:
    target = to_asyncpg_url("postgres://u:p@ep-x.aws.neon.tech/db")
    assert target.connect_args == {"ssl": "require"}


def test_local_url_keeps_other_params() -> None:
    target = to_asyncpg_url("postgresql://u:p@localhost:5432/db?application_name=tr")
    assert target.url == "postgresql+asyncpg://u:p@localhost:5432/db?application_name=tr"
    assert target.connect_args == {}


def test_rejects_other_schemes() -> None:
    with pytest.raises(ValueError, match="scheme"):
        to_asyncpg_url("mysql://u:p@h/db")


@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_fake_auth_refused_outside_local(env: Environment) -> None:
    with pytest.raises(ValidationError, match="only allowed"):
        Settings(environment=env, auth_provider=AuthProvider.FAKE, _env_file=None)  # type: ignore[call-arg]


def test_clerk_needs_issuer_in_production() -> None:
    with pytest.raises(ValidationError, match="CLERK_ISSUER"):
        Settings(
            environment=Environment.PRODUCTION, auth_provider=AuthProvider.CLERK, _env_file=None
        )  # type: ignore[call-arg]


@pytest.mark.parametrize("parties", ["", " , "])
@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_clerk_needs_authorized_parties_outside_local(env: Environment, parties: str) -> None:
    with pytest.raises(ValidationError, match="CLERK_AUTHORIZED_PARTIES"):
        Settings(
            environment=env,
            auth_provider=AuthProvider.CLERK,
            clerk_issuer="https://example.clerk.accounts.dev",
            clerk_authorized_parties=parties,
            _env_file=None,
        )  # type: ignore[call-arg]


# Everything a production deployment must set besides auth.
REAL_PROVIDERS: dict[str, object] = {
    "embeddings_provider": EmbeddingsProvider.VERTEX,
    "llm_provider": LLMProvider.VERTEX,
    "parser_provider": ParserProvider.DOCLING,
    "storage_provider": StorageProvider.GCS,
    "gcs_bucket": "tr-docs",
    "vertex_project": "tr-prod",
    "celery_task_always_eager": False,
}


def test_clerk_with_issuer_and_parties_is_accepted_in_production() -> None:
    s = Settings(
        environment=Environment.PRODUCTION,
        auth_provider=AuthProvider.CLERK,
        clerk_issuer="https://example.clerk.accounts.dev",
        clerk_authorized_parties="https://app.example.com",
        _env_file=None,
        **REAL_PROVIDERS,
    )  # type: ignore[call-arg]
    assert s.authorized_parties == ["https://app.example.com"]


@pytest.mark.parametrize("env", [Environment.LOCAL, Environment.TEST])
def test_clerk_without_parties_allowed_locally(env: Environment) -> None:
    Settings(environment=env, auth_provider=AuthProvider.CLERK, _env_file=None)  # type: ignore[call-arg]


PROD_AUTH: dict[str, object] = {
    "auth_provider": AuthProvider.CLERK,
    "clerk_issuer": "https://example.clerk.accounts.dev",
    "clerk_authorized_parties": "https://app.example.com",
}


@pytest.mark.parametrize(
    "fake",
    [
        {"embeddings_provider": EmbeddingsProvider.FAKE},
        {"llm_provider": LLMProvider.FAKE},
        {"parser_provider": ParserProvider.FAKE},
        {"storage_provider": StorageProvider.LOCAL},
        {"storage_provider": StorageProvider.MEMORY},
    ],
    ids=["embeddings", "llm", "parser", "storage-local", "storage-memory"],
)
@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_fake_providers_refused_outside_local(env: Environment, fake: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="only allowed when ENVIRONMENT is local or test"):
        Settings(environment=env, _env_file=None, **{**PROD_AUTH, **REAL_PROVIDERS, **fake})  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["embeddings_location", "llm_location"])
@pytest.mark.parametrize("location", ["global", "us-central1", "asia-northeast1"])
def test_vertex_location_must_be_eu(field: str, location: str) -> None:
    with pytest.raises(ValidationError, match="must run in an EU location"):
        Settings(
            environment=Environment.TEST,
            _env_file=None,
            **{**REAL_PROVIDERS, field: location},  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("location", ["europe-west3", "europe-west4", "eu"])
def test_eu_vertex_locations_are_accepted(location: str) -> None:
    s = Settings(
        environment=Environment.TEST,
        _env_file=None,
        **{**REAL_PROVIDERS, "embeddings_location": location, "llm_location": location},  # type: ignore[arg-type]
    )
    assert s.embedding_model_key == "vertex/gemini-embedding-001@768"


def test_vertex_needs_a_project() -> None:
    with pytest.raises(ValidationError, match="VERTEX_PROJECT"):
        Settings(
            environment=Environment.TEST,
            _env_file=None,
            **{**REAL_PROVIDERS, "vertex_project": None},  # type: ignore[arg-type]
        )
