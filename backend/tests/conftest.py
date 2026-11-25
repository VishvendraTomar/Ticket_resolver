"""Shared fixtures.

Unit tests run offline. Tests marked ``db`` need DATABASE_URL (owner) and
APP_DATABASE_URL (app_user); without them they are skipped with a reason.
They write uniquely named data and never truncate (ADR-0001).
"""

from __future__ import annotations

import os

# Force the test environment before the app (and its settings) are imported.
os.environ["ENVIRONMENT"] = "test"
os.environ["AUTH_PROVIDER"] = "fake"

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.db import get_engine, make_engine
from app.main import create_app
from app.providers.auth.fake import make_fake_token

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _db_configured() -> bool:
    s = get_settings()
    return s.database_url is not None and s.app_database_url is not None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _db_configured():
        return
    if os.environ.get("REQUIRE_DB_TESTS") == "1":
        # CI sets this: a missing database must fail the build, not skip the RLS suite.
        raise pytest.UsageError(
            "REQUIRE_DB_TESTS=1 but DATABASE_URL / APP_DATABASE_URL are not set"
        )
    skip = pytest.mark.skip(
        reason="DB tests need DATABASE_URL and APP_DATABASE_URL (see .env.example, ADR-0001)"
    )
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def migrated() -> None:
    """Bring the database to head once per test session (as the owner role)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
async def owner_engine(migrated: None) -> AsyncIterator[AsyncEngine]:
    url = get_settings().database_url
    assert url is not None
    engine = make_engine(url.get_secret_value())
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def app_engine(migrated: None) -> AsyncIterator[AsyncEngine]:
    engine = get_engine()
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def client(app_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@dataclass(frozen=True)
class Person:
    subject: str
    email: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def new_person(label: str) -> Person:
    """A unique identity per call, so tests never collide in a shared database."""
    suffix = uuid.uuid4().hex[:12]
    subject = f"test_{label}_{suffix}"
    email = f"{label}.{suffix}@example.com"
    return Person(subject=subject, email=email, token=make_fake_token(subject, email, label))


async def sign_in(client: AsyncClient, person: Person) -> dict[str, object]:
    response = await client.get("/v1/me", headers=person.headers)
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def create_workspace(client: AsyncClient, owner: Person, name: str) -> str:
    response = await client.post("/v1/workspaces", json={"name": name}, headers=owner.headers)
    assert response.status_code == 201, response.text
    workspace_id: str = response.json()["id"]
    return workspace_id


async def add_member(
    client: AsyncClient, actor: Person, workspace_id: str, member: Person, role: str
) -> str:
    response = await client.post(
        f"/v1/workspaces/{workspace_id}/members",
        json={"email": member.email, "role": role},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    membership_id: str = response.json()["id"]
    return membership_id


@dataclass(frozen=True)
class World:
    """Two workspaces. Alice owns A. Bob owns B; Carol is an agent in B."""

    alice: Person
    bob: Person
    carol: Person
    ws_a: str
    ws_b: str
    alice_membership_a: str
    carol_membership_b: str


@pytest.fixture
async def world(client: AsyncClient) -> World:
    alice, bob, carol = new_person("alice"), new_person("bob"), new_person("carol")
    for p in (alice, bob, carol):
        await sign_in(client, p)
    ws_a = await create_workspace(client, alice, "Workspace A")
    ws_b = await create_workspace(client, bob, "Workspace B")
    carol_membership_b = await add_member(client, bob, ws_b, carol, "agent")

    members_a = (await client.get(f"/v1/workspaces/{ws_a}/members", headers=alice.headers)).json()
    return World(
        alice=alice,
        bob=bob,
        carol=carol,
        ws_a=ws_a,
        ws_b=ws_b,
        alice_membership_a=members_a[0]["id"],
        carol_membership_b=carol_membership_b,
    )
