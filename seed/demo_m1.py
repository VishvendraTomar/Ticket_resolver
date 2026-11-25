"""M1 demo: two workspaces, people in each, and proof that A cannot see B.

Run (Compose Postgres up, migrations applied):

    cd backend && uv run python ../seed/demo_m1.py
    cd backend && uv run python ../seed/demo_m1.py --api-url http://localhost:8000

By default the FastAPI app runs in-process (fake auth, real Postgres). With
--api-url it talks to a running API, which must have AUTH_PROVIDER=fake.
Either way the raw-SQL checks connect as app_user (APP_DATABASE_URL), exactly
as the app does. Safe to re-run: it reuses the same demo people and workspaces.

Exit code 0 only if every isolation check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# In-process mode uses fake auth. Settings still refuse it unless ENVIRONMENT
# is local or test, so this can't switch a real deployment to fake auth.
os.environ["AUTH_PROVIDER"] = "fake"

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import get_engine, make_engine  # noqa: E402
from app.providers.auth.fake import make_fake_token  # noqa: E402

WORKSPACE_A = "Northwind Global (demo)"
WORKSPACE_B = "Contoso Benefits (demo)"


@dataclass(frozen=True)
class Person:
    key: str
    name: str
    email: str

    @property
    def headers(self) -> dict[str, str]:
        token = make_fake_token(f"demo_{self.key}", self.email, self.name)
        return {"Authorization": f"Bearer {token}"}


ALICE = Person("alice", "Alice Andersen", "alice@northwind.example.com")
DANA = Person("dana", "Dana Dubois", "dana@northwind.example.com")
ERIN = Person("erin", "Erin Eriksen", "erin@northwind.example.com")
BOB = Person("bob", "Bob Brandt", "bob@contoso.example.com")
CAROL = Person("carol", "Carol Costa", "carol@contoso.example.com")

# No WHERE clauses: only RLS stands between these queries and other tenants.
COUNT_ALL = {
    "workspaces": "SELECT count(*) FROM workspaces",
    "memberships": "SELECT count(*) FROM memberships",
    "audit_events": "SELECT count(*) FROM audit_events",
}
WORKSPACE_IDS = {
    "workspaces": "SELECT DISTINCT id FROM workspaces",
    "memberships": "SELECT DISTINCT workspace_id FROM memberships",
    "audit_events": "SELECT DISTINCT workspace_id FROM audit_events",
}

PLAN: dict[str, tuple[Person, list[tuple[Person, str]]]] = {
    WORKSPACE_A: (ALICE, [(DANA, "admin"), (ERIN, "agent")]),
    WORKSPACE_B: (BOB, [(CAROL, "agent")]),
}


class Demo:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.failures = 0

    async def call(
        self, person: Person, method: str, path: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        return await self.client.request(method, path, json=body, headers=person.headers)

    async def ok(
        self, person: Person, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        r = await self.call(person, method, path, body)
        if r.status_code >= 400:
            raise RuntimeError(f"{person.name}: {method} {path} -> {r.status_code} {r.text}")
        return r.json() if r.content else None

    def check(self, label: str, passed: bool, detail: str = "") -> None:
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {label}" + (f"  ({detail})" if detail else ""))
        if not passed:
            self.failures += 1

    async def expect_status(
        self, label: str, expected: int, call: Callable[[], Awaitable[httpx.Response]]
    ) -> None:
        r = await call()
        self.check(label, r.status_code == expected, f"HTTP {r.status_code}")


async def set_up(demo: Demo) -> dict[str, str]:
    """Create (or reuse) both workspaces and their members. Returns name -> id."""
    print("1. People sign in (first sign-in creates their user row)")
    for p in (ALICE, DANA, ERIN, BOB, CAROL):
        await demo.ok(p, "GET", "/v1/me")
        print(f"   - {p.name} <{p.email}>")

    print("\n2. Each owner creates a workspace and adds their team")
    ids: dict[str, str] = {}
    for ws_name, (owner, members) in PLAN.items():
        me = await demo.ok(owner, "GET", "/v1/me")
        existing = [w for w in me["workspaces"] if w["name"] == ws_name and w["role"] == "owner"]
        if existing:
            ws_id = existing[0]["id"]
            print(f"   - {owner.name} reuses '{ws_name}'")
        else:
            ws_id = (await demo.ok(owner, "POST", "/v1/workspaces", {"name": ws_name}))["id"]
            print(f"   - {owner.name} creates '{ws_name}'")
        ids[ws_name] = ws_id
        for member, role in members:
            r = await demo.call(
                owner,
                "POST",
                f"/v1/workspaces/{ws_id}/members",
                {"email": member.email, "role": role},
            )
            if r.status_code == 409:  # already a member from a previous run
                print(f"     {member.name} is already a member")
            elif r.status_code == 201:
                print(f"     adds {member.name} as {role}")
            else:
                raise RuntimeError(f"add {member.email}: {r.status_code} {r.text}")
    return ids


async def show_views(demo: Demo, ids: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    print("\n3. What each owner sees")
    members: dict[str, list[dict[str, Any]]] = {}
    for ws_name, (owner, _) in PLAN.items():
        rows = await demo.ok(owner, "GET", f"/v1/workspaces/{ids[ws_name]}/members")
        members[ws_name] = rows
        print(f"   {owner.name} in '{ws_name}':")
        for m in rows:
            print(f"     - {m['user']['name']:<16} {m['role']}")
    return members


async def api_checks(
    demo: Demo, ids: dict[str, str], members: dict[str, list[dict[str, Any]]]
) -> None:
    a, b = ids[WORKSPACE_A], ids[WORKSPACE_B]
    carol_in_b = next(m["id"] for m in members[WORKSPACE_B] if m["user"]["email"] == CAROL.email)

    print("\n4. Isolation through the API (Alice is owner of A, not a member of B)")
    await demo.expect_status(
        "Alice reads workspace B -> 404",
        404,
        lambda: demo.call(ALICE, "GET", f"/v1/workspaces/{b}"),
    )
    await demo.expect_status(
        "Alice lists B's members -> 404",
        404,
        lambda: demo.call(ALICE, "GET", f"/v1/workspaces/{b}/members"),
    )
    await demo.expect_status(
        "Alice adds herself to B -> 404",
        404,
        lambda: demo.call(
            ALICE, "POST", f"/v1/workspaces/{b}/members", {"email": ALICE.email, "role": "owner"}
        ),
    )
    await demo.expect_status(
        "Alice changes Carol's B membership via A's URL -> 404",
        404,
        lambda: demo.call(
            ALICE, "PATCH", f"/v1/workspaces/{a}/members/{carol_in_b}", {"role": "viewer"}
        ),
    )
    await demo.expect_status(
        "Alice removes Carol's B membership via A's URL -> 404",
        404,
        lambda: demo.call(ALICE, "DELETE", f"/v1/workspaces/{a}/members/{carol_in_b}"),
    )
    carol_ws = {w["id"] for w in (await demo.ok(CAROL, "GET", "/v1/me"))["workspaces"]}
    demo.check("Carol's /v1/me lists B and not A", b in carol_ws and a not in carol_ws)
    roster_b = await demo.ok(BOB, "GET", f"/v1/workspaces/{b}/members")
    demo.check(
        "Carol's membership in B is unchanged",
        any(m["id"] == carol_in_b and m["role"] == "agent" for m in roster_b),
    )


async def sql_checks(demo: Demo, ids: dict[str, str]) -> None:
    """Below the API: raw SQL as app_user, with only RLS between A and B."""
    url = get_settings().app_database_url
    if url is None:
        raise RuntimeError("APP_DATABASE_URL is not set")
    a, b = uuid.UUID(ids[WORKSPACE_A]), uuid.UUID(ids[WORKSPACE_B])
    engine = make_engine(url.get_secret_value())
    print("\n5. Isolation in the database (raw SQL as app_user; no WHERE clauses)")
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                for table, count_sql in COUNT_ALL.items():
                    n = (await conn.execute(text(count_sql))).scalar_one()
                    demo.check(f"no context: {table} shows nothing", n == 0, f"{n} rows")

            async with conn.begin():
                await conn.execute(
                    text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(a)}
                )
                for table, ids_sql in WORKSPACE_IDS.items():
                    seen = {r[0] for r in await conn.execute(text(ids_sql))}
                    demo.check(
                        f"context A: {table} shows only A", seen == {a}, f"{len(seen)} workspace(s)"
                    )
                n_b = (
                    await conn.execute(
                        text("SELECT count(*) FROM memberships WHERE workspace_id = :b"), {"b": b}
                    )
                ).scalar_one()
                demo.check("context A: asking for B's memberships by id returns 0", n_b == 0)

            try:
                async with conn.begin():
                    await conn.execute(
                        text("SELECT set_config('app.workspace_id', :w, true)"), {"w": str(a)}
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO audit_events (id, workspace_id, action, target_type)"
                            " VALUES (:id, :b, 'demo.forged', 'workspace')"
                        ),
                        {"id": uuid.uuid4(), "b": b},
                    )
                demo.check("context A: writing a row into B is rejected", False, "insert succeeded")
            except DBAPIError as exc:
                demo.check(
                    "context A: writing a row into B is rejected",
                    "row-level security" in str(exc.orig).lower(),
                    "RLS WITH CHECK",
                )
    finally:
        await engine.dispose()


async def run(api_url: str | None) -> int:
    if api_url:
        client = httpx.AsyncClient(base_url=api_url.rstrip("/"), timeout=10)
    else:
        from app.main import create_app

        transport = httpx.ASGITransport(app=create_app())
        client = httpx.AsyncClient(transport=transport, base_url="http://demo")

    try:
        async with client:
            demo = Demo(client)
            where = api_url or "in-process app"
            print(f"M1 demo against {where}, database via APP_DATABASE_URL\n")
            ids = await set_up(demo)
            members = await show_views(demo, ids)
            await api_checks(demo, ids, members)
        await sql_checks(demo, ids)
    finally:
        if not api_url:
            await get_engine().dispose()

    print()
    if demo.failures:
        print(f"FAILED: {demo.failures} isolation check(s) failed")
        return 1
    print("All isolation checks passed: workspace A cannot see or change B's data.")
    return 0


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # keep the demo output readable
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", help="talk to a running API instead of in-process")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.api_url)))


if __name__ == "__main__":
    main()
