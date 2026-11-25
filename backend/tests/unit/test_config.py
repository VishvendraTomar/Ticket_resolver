from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import AuthProvider, Environment, Settings, to_asyncpg_url


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


def test_clerk_with_issuer_and_parties_is_accepted_in_production() -> None:
    s = Settings(
        environment=Environment.PRODUCTION,
        auth_provider=AuthProvider.CLERK,
        clerk_issuer="https://example.clerk.accounts.dev",
        clerk_authorized_parties="https://app.example.com",
        _env_file=None,
    )  # type: ignore[call-arg]
    assert s.authorized_parties == ["https://app.example.com"]


@pytest.mark.parametrize("env", [Environment.LOCAL, Environment.TEST])
def test_clerk_without_parties_allowed_locally(env: Environment) -> None:
    Settings(environment=env, auth_provider=AuthProvider.CLERK, _env_file=None)  # type: ignore[call-arg]
