"""docs/failure-modes/ingestion.md #15 — the coverage map."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import World
from tests.knowledge.helpers import confirm, published_version, topic_id, upload

pytestmark = pytest.mark.db


async def test_coverage_counts_published_only(client: AsyncClient, world: World) -> None:
    await published_version(client, world.bob, world.ws_b, jurisdiction="DE", topic="leave")
    draft = await upload(client, world.bob, world.ws_b, title="France draft")
    await confirm(client, world.bob, world.ws_b, draft["versions"][0]["id"], jurisdiction="FR")

    body = (
        await client.get(f"/v1/workspaces/{world.ws_b}/coverage", headers=world.bob.headers)
    ).json()
    leave = await topic_id(client, world.bob, world.ws_b, "leave")
    cells = {(c["jurisdiction_code"], c["topic_id"]): c for c in body["cells"]}
    assert cells[("DE", leave)]["sections"] == 3
    assert cells[("DE", leave)]["documents"] == 1
    assert not any(code == "FR" for code, _ in cells)  # a draft is not coverage
    codes = [j["code"] for j in body["jurisdictions"]]
    # Rows: every jurisdiction in use (drafts too, so gaps show) and their ancestors.
    assert codes == ["GLOBAL", "EU", "DE", "FR"]
    assert len(body["topics"]) == 10
