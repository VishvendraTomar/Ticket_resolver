"""docs/failure-modes/ingestion.md — uploads, dedupe, permissions, retry."""

from __future__ import annotations

import io
import zipfile

import pytest
from httpx import AsyncClient

from app.providers.parser.fake import FakeParser
from tests.conftest import World, add_member, new_person, sign_in
from tests.knowledge.helpers import (
    POLICY_MD,
    add_version,
    get_version,
    rows,
    unique_md,
    upload,
)

pytestmark = pytest.mark.db


async def test_upload_parses_and_awaits_review(client: AsyncClient, world: World) -> None:
    doc = await upload(client, world.bob, world.ws_b, unique_md())
    version = await get_version(client, world.bob, world.ws_b, doc["versions"][0]["id"])
    assert version["pipeline_status"] == "awaiting_review"
    assert version["status"] == "draft"
    report = version["parse_report"]
    assert report["parser"] == "fake-markdown 1"
    assert report["sections"] == 3
    assert report["tables"] == 1
    assert version["tag_suggestions"]["status"] == "ok"
    sections = (
        await client.get(
            f"/v1/workspaces/{world.ws_b}/versions/{version['id']}/sections",
            headers=world.bob.headers,
        )
    ).json()
    assert [s["clause_number"] for s in sections] == ["1", "2", "Annex B"]
    scope_refs = sections[0]["refs"]
    assert scope_refs == [{"target_text": "Annex B", "to_section_id": sections[2]["id"]}]


async def test_identical_file_is_rejected(client: AsyncClient, world: World) -> None:
    md = unique_md()
    doc = await upload(client, world.bob, world.ws_b, md)
    r = await add_version(client, world.bob, world.ws_b, doc["id"], md)
    assert r.status_code == 409
    assert r.json()["error"]["details"]["existing_version_id"] == doc["versions"][0]["id"]
    r2 = await add_version(client, world.bob, world.ws_b, doc["id"])
    assert r2.status_code == 201
    assert r2.json()["version_number"] == 2


def _docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


async def test_upload_rejects_oversize_and_unknown_types(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def post(name: str, data: bytes) -> int:
        r = await client.post(
            f"/v1/workspaces/{world.ws_b}/documents",
            data={"title": "x"},
            files={"file": (name, data, "application/octet-stream")},
            headers=world.bob.headers,
        )
        return r.status_code

    assert await post("evil.pdf", b"MZ\x90\x00 windows executable") == 415  # name lies
    assert await post("notes.txt.exe", b"\xff\xfe\x00binary") == 415
    assert await post("plain.csv", b"a,b,c\n1,2,3\n") == 415
    assert await post("empty.md", b"") == 415
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    assert await post("big.md", b"# T\n\n" + b"x" * (1024 * 1024 + 10)) == 413
    # Content decides the type; these are accepted (and parsed by the fake parser).
    from app.knowledge.uploads import detect_mime

    assert detect_mime(_docx(), "whatever.bin").endswith("wordprocessingml.document")
    assert detect_mime(b"%PDF-1.7\n...", "x") == "application/pdf"
    assert detect_mime(b"<!DOCTYPE html><html><body>x", "page.txt") == "text/html"


async def test_only_editors_can_write(client: AsyncClient, world: World) -> None:
    # Carol is an agent in B: read-only for the knowledge base.
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/documents",
        data={"title": "x"},
        files={"file": ("a.md", unique_md().encode(), "text/markdown")},
        headers=world.carol.headers,
    )
    assert r.status_code == 403
    assert (
        await client.get(f"/v1/workspaces/{world.ws_b}/documents", headers=world.carol.headers)
    ).status_code == 200
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/glossary", json={"term": "PTO"}, headers=world.carol.headers
    )
    assert r.status_code == 403
    # A policy editor may upload; configuring topics is for owners/admins.
    dana = new_person("dana")
    await sign_in(client, dana)
    await add_member(client, world.bob, world.ws_b, dana, "policy_editor")
    await upload(client, dana, world.ws_b)
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/topics", json={"key": "bonus", "name": "Bonus"},
        headers=dana.headers,
    )  # fmt: skip
    assert r.status_code == 403


async def test_retry_requeues_failed_version(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch, app_engine: object
) -> None:
    monkeypatch.setattr("workers.tasks.get_parser", lambda: FakeParser(fail_with="encrypted PDF"))
    doc = await upload(client, world.bob, world.ws_b)
    vid = doc["versions"][0]["id"]
    version = await get_version(client, world.bob, world.ws_b, vid)
    assert version["pipeline_status"] == "failed"
    assert "encrypted PDF" in version["pipeline_error"]
    failures = (
        await client.get(f"/v1/workspaces/{world.ws_b}/job-failures", headers=world.bob.headers)
    ).json()
    assert any(f["version_id"] == vid and f["resolved_at"] is None for f in failures)

    monkeypatch.setattr("workers.tasks.get_parser", lambda: FakeParser())
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/versions/{vid}/retry", headers=world.bob.headers
    )
    assert r.status_code == 200, r.text
    assert (await get_version(client, world.bob, world.ws_b, vid))[
        "pipeline_status"
    ] == "awaiting_review"
    failures = (
        await client.get(f"/v1/workspaces/{world.ws_b}/job-failures", headers=world.bob.headers)
    ).json()
    assert all(f["resolved_at"] is not None for f in failures if f["version_id"] == vid)
    r = await client.post(
        f"/v1/workspaces/{world.ws_b}/versions/{vid}/retry", headers=world.bob.headers
    )
    assert r.status_code == 409  # nothing to retry now


async def test_policy_md_fixture_is_stable() -> None:
    assert POLICY_MD.count("##") == 3
    assert rows  # imported for other modules
