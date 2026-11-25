"""M2 demo: the Northwind Global knowledge base, ingested end to end.

    cd backend && uv run python ../seed/demo_m2.py
    cd backend && uv run python ../seed/demo_m2.py --api-url http://localhost:8000

Uploads the clean-room corpus in seed/northwind/ (14 documents: GLOBAL, EU, DE,
DE-BY, FR, ES, GB, IN, US-CA, US-NY), waits for parsing, confirms tags as an
editor would, publishes, then runs a mid-year policy change. Prints the
coverage map and checks the M2 invariants. Safe to re-run.

In-process (default): the FastAPI app with ingestion jobs run inline, the real
Docling parser, and fake LLM/embeddings unless Vertex AI is configured.
With --api-url: a running API plus a Celery worker (e.g. compose --profile app).

Exit code 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
CORPUS = Path(__file__).resolve().parent / "northwind"
sys.path.insert(0, str(BACKEND_DIR))

# In-process mode: fake auth, jobs inline. Settings still refuse both outside local/test.
os.environ["AUTH_PROVIDER"] = "fake"
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")

import httpx  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.providers.auth.fake import make_fake_token  # noqa: E402

WORKSPACE = "Northwind Global (M2 demo)"
OWNER = ("demo_m2_owner", "hr.ops@northwind.example.com", "Hanna Ops")
OUTSIDER = ("demo_m2_outsider", "someone@contoso.example.com", "Outsider")
EMPLOYEE = {"worker_type": "employee"}
JAN_1 = date(2026, 1, 1)
JUL_1 = date(2026, 7, 1)


@dataclass
class Doc:
    key: str
    file: str
    title: str
    jurisdiction: str
    topic: str
    scope: dict[str, str] = field(default_factory=dict)
    effective_from: date = JAN_1
    # heading (prefix) -> (jurisdiction, topic) for sections that differ (PLAN §4.2)
    sections: dict[str, tuple[str, str]] = field(default_factory=dict)
    supersedes: list[str] = field(default_factory=list)
    supplements: list[str] = field(default_factory=list)


# Publish order matters: relations point at versions that must already exist.
DOCS = [
    Doc(
        "global-leave",
        "global-leave.md",
        "Northwind Global Leave Policy",
        "GLOBAL",
        "leave",
        EMPLOYEE,
    ),
    Doc("eu-leave", "eu-leave-minimum.html", "Northwind EU Leave Minimum", "EU", "leave"),
    Doc(
        "de-leave",
        "de-leave.md",
        "Northwind Leave Policy — Germany",
        "DE",
        "leave",
        EMPLOYEE,
        sections={"Annex Munich office": ("DE-BY", "public_holidays")},
        supersedes=["global-leave"],
        supplements=["eu-leave"],
    ),
    Doc(
        "fr-leave",
        "fr-leave.md",
        "Northwind Leave Policy — France",
        "FR",
        "leave",
        EMPLOYEE,
        supersedes=["global-leave"],
        supplements=["eu-leave"],
    ),
    Doc(
        "es-leave",
        "es-leave.md",
        "Northwind Leave Policy — Spain",
        "ES",
        "leave",
        EMPLOYEE,
        supersedes=["global-leave"],
        supplements=["eu-leave"],
    ),
    Doc(
        "gb-leave",
        "gb-leave.md",
        "Northwind Leave Policy — United Kingdom",
        "GB",
        "leave",
        EMPLOYEE,
        supersedes=["global-leave"],
    ),
    Doc(
        "de-sick",
        "de-sick-pay.md",
        "Northwind Sick Pay Policy — Germany",
        "DE",
        "sick_pay",
        EMPLOYEE,
    ),
    Doc(
        "gb-sick",
        "gb-sick-pay.md",
        "Northwind Sick Pay Policy — United Kingdom",
        "GB",
        "sick_pay",
        EMPLOYEE,
    ),
    Doc(
        "gb-notice",
        "gb-notice.md",
        "Northwind Notice Periods — United Kingdom",
        "GB",
        "notice_period",
        EMPLOYEE,
    ),
    Doc(
        "in-payroll", "in-payroll.md", "Northwind Payroll Policy — India", "IN", "payroll", EMPLOYEE
    ),
    Doc(
        "ca-sick",
        "us-ca-sick-pay.md",
        "Northwind Sick Leave Policy — California",
        "US-CA",
        "sick_pay",
        EMPLOYEE,
    ),
    Doc(
        "ca-payroll",
        "us-ca-payroll.md",
        "Northwind Payroll Policy — California",
        "US-CA",
        "payroll",
        EMPLOYEE,
    ),
    Doc(
        "ny-sick",
        "us-ny-sick-pay.md",
        "Northwind Sick Leave Policy — New York",
        "US-NY",
        "sick_pay",
        EMPLOYEE,
    ),
    Doc(
        "expenses",
        "global-expenses-v1.md",
        "Northwind Global Expenses Policy",
        "GLOBAL",
        "expenses",
    ),
]

GLOSSARY = [
    ("annual leave", ["PTO", "holiday", "vacation", "congés payés", "Urlaub", "vacaciones"]),
    ("sick pay", ["SSP", "Krankengeld", "sick leave", "Entgeltfortzahlung"]),
    ("notice period", ["notice", "Kündigungsfrist"]),
]

IN_PROGRESS = {"queued", "parsing", "tagging", "embedding"}


def headers(person: tuple[str, str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_fake_token(*person)}"}


class Demo:
    def __init__(self, client: httpx.AsyncClient, poll: bool, workspace_name: str) -> None:
        self.client = client
        self.workspace_name = workspace_name
        self.poll = poll
        self.failures = 0
        self.h = headers(OWNER)
        self.ws = ""

    def check(self, label: str, passed: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))
        self.failures += 0 if passed else 1

    async def req(self, method: str, path: str, expect: tuple[int, ...] = (200,), **kw: Any) -> Any:
        url = path if path.startswith("/v1/me") else f"/v1/workspaces/{self.ws}{path}"
        r = await self.client.request(method, url, headers=self.h, **kw)
        if r.status_code not in expect:
            raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None

    async def wait(self, version_id: str, until: set[str], limit_s: float = 300) -> dict[str, Any]:
        deadline = time.monotonic() + limit_s
        while True:
            v: dict[str, Any] = await self.req("GET", f"/versions/{version_id}")
            if v["pipeline_status"] in until:
                return v
            if v["pipeline_status"] == "failed":
                raise RuntimeError(f"version {version_id} failed: {v['pipeline_error']}")
            if not self.poll or time.monotonic() > deadline:
                raise RuntimeError(f"version {version_id} stuck in {v['pipeline_status']}")
            await asyncio.sleep(1)


async def setup_workspace(demo: Demo) -> None:
    me = (await demo.client.get("/v1/me", headers=demo.h)).json()
    existing = [w for w in me["workspaces"] if w["name"] == demo.workspace_name]
    if existing:
        demo.ws = existing[0]["id"]
        print(f"Reusing workspace '{demo.workspace_name}'")
    else:
        r = await demo.client.post(
            "/v1/workspaces", json={"name": demo.workspace_name}, headers=demo.h
        )
        demo.ws = r.json()["id"]
        print(f"Created workspace '{demo.workspace_name}'")
    await demo.req(
        "POST",
        "/scope-fields",
        expect=(201, 409),
        json={
            "key": "worker_type",
            "name": "Worker type",
            "allowed_values": ["employee", "contractor"],
        },
    )
    for term, synonyms in GLOSSARY:
        await demo.req(
            "POST", "/glossary", expect=(201, 409), json={"term": term, "synonyms": synonyms}
        )


def _mime(file: str) -> str:
    return "text/html" if file.endswith(".html") else "text/markdown"


async def ingest(demo: Demo, doc: Doc, topics: dict[str, str], published: dict[str, str]) -> str:
    """Upload → review tags → publish. Returns the published version id."""
    documents = await demo.req("GET", "/documents")
    found = next((d for d in documents if d["title"] == doc.title), None)
    if found and found["latest_version"]["status"] == "published":
        # Each entry describes a document's first version (later ones are explicit steps).
        detail = await demo.req("GET", f"/documents/{found['id']}")
        first = next(v for v in detail["versions"] if v["version_number"] == 1)
        print(f"  = {doc.title}: already published")
        return str(first["id"])
    if found:
        version_id = found["latest_version"]["id"]
    else:
        data = (CORPUS / doc.file).read_bytes()
        body = await demo.req(
            "POST",
            "/documents",
            expect=(201,),
            data={"title": doc.title, "language": "en", "source": f"seed/northwind/{doc.file}"},
            files={"file": (doc.file, data, _mime(doc.file))},
        )
        version_id = body["versions"][0]["id"]
    version = await demo.wait(version_id, {"awaiting_review", "ready"})
    report = version["parse_report"]
    sections = await demo.req("GET", f"/versions/{version_id}/sections")
    overrides = []
    for s in sections:
        heading = " › ".join(s["heading_path"]) or (s["title"] or "")
        for prefix, (code, topic) in doc.sections.items():
            if heading.startswith(prefix) or (s["title"] or "").startswith(prefix):
                overrides.append(
                    {"section_id": s["id"], "jurisdiction_code": code, "topic_id": topics[topic]}
                )
    await demo.req(
        "PUT",
        f"/versions/{version_id}/tags",
        json={
            "jurisdiction_code": doc.jurisdiction,
            "scope": doc.scope,
            "topic_id": topics[doc.topic],
            "effective_from": doc.effective_from.isoformat(),
            "sections": overrides,
        },
    )
    await demo.wait(version_id, {"ready"})
    await demo.req(
        "POST",
        f"/versions/{version_id}/publish",
        json={
            "acknowledge_conflicts": True,
            "supersedes": [published[k] for k in doc.supersedes],
            "supplements": [published[k] for k in doc.supplements],
        },
    )
    print(
        f"  + {doc.title}: {report['parser']}, {report['sections']} sections, "
        f"{report['chunks']} chunks → {doc.jurisdiction}/{doc.topic}, published"
    )
    return str(version_id)


async def midyear_change(demo: Demo, published: dict[str, str]) -> str:
    """Expenses v2 from 1 July 2026 closes v1 automatically (ingestion.md #9)."""
    documents = await demo.req("GET", "/documents")
    expenses = next(d for d in documents if d["title"] == "Northwind Global Expenses Policy")
    detail = await demo.req("GET", f"/documents/{expenses['id']}")
    v2 = next((v for v in detail["versions"] if v["version_number"] == 2), None)
    if v2 and v2["status"] == "published":
        print("  = Expenses v2 (from 2026-07-01): already published")
        return str(v2["id"])
    if v2 is None:
        data = (CORPUS / "global-expenses-v2.md").read_bytes()
        v2 = await demo.req(
            "POST",
            f"/documents/{expenses['id']}/versions",
            expect=(201,),
            files={"file": ("global-expenses-v2.md", data, "text/markdown")},
        )
    await demo.wait(v2["id"], {"awaiting_review", "ready"})
    topics = {t["key"]: t["id"] for t in await demo.req("GET", "/topics")}
    await demo.req(
        "PUT",
        f"/versions/{v2['id']}/tags",
        json={
            "jurisdiction_code": "GLOBAL",
            "scope": {},
            "topic_id": topics["expenses"],
            "effective_from": JUL_1.isoformat(),
            "sections": [],
        },
    )
    await demo.wait(v2["id"], {"ready"})
    await demo.req(
        "POST",
        f"/versions/{v2['id']}/publish",
        json={"acknowledge_conflicts": True, "supersedes": [published["expenses"]]},
    )
    print("  + Expenses v2 (from 2026-07-01): published; v1 closed on 2026-06-30")
    return str(v2["id"])


async def print_coverage(demo: Demo) -> dict[tuple[str, str], int]:
    cov = await demo.req("GET", "/coverage")
    topics = {t["id"]: t["key"] for t in cov["topics"]}
    cells = {
        (c["jurisdiction_code"], topics.get(c["topic_id"], "-")): c["sections"]
        for c in cov["cells"]
    }
    shown = ["leave", "sick_pay", "notice_period", "payroll", "expenses", "public_holidays"]
    print("\nCoverage (published sections per jurisdiction and topic; '·' = gap)")
    print(f"  {'':<8}" + "".join(f"{t[:12]:>14}" for t in shown))
    for j in cov["jurisdictions"]:
        row = "".join(f"{cells.get((j['code'], t), '·'):>14}" for t in shown)
        print(f"  {j['code']:<8}{row}")
    return cells


async def checks(
    demo: Demo, published: dict[str, str], v2: str, cells: dict[tuple[str, str], int]
) -> None:
    print("\nChecks")
    documents = await demo.req("GET", "/documents")
    titles = {d["title"]: d for d in documents}
    demo.check(
        "all 14 Northwind documents are published",
        all(
            titles.get(d.title, {}).get("latest_version", {}).get("status") == "published"
            for d in DOCS
        ),
        f"{len(documents)} documents",
    )
    v1 = await demo.req("GET", f"/versions/{published['expenses']}")
    v2d = await demo.req("GET", f"/versions/{v2}")
    demo.check(
        "mid-year change: expenses v1 ends where v2 starts",
        v1["effective_to"] == "2026-07-01"
        and v2d["effective_from"] == "2026-07-01"
        and v2d["effective_to"] is None,
        f"v1 {v1['effective_from']}→{v1['effective_to']}, v2 from {v2d['effective_from']}",
    )
    de = await demo.req("GET", f"/versions/{published['de-leave']}")
    rel = {(r["kind"], r["to_version_id"]) for r in de["relations"]}
    demo.check(
        "override + supplement recorded: DE leave supersedes Global, supplements EU",
        ("supersedes", published["global-leave"]) in rel
        and ("supplements", published["eu-leave"]) in rel,
    )
    de_sections = await demo.req("GET", f"/versions/{published['de-leave']}/sections")
    annex = next(s for s in de_sections if (s["title"] or "").startswith("Annex Munich"))
    demo.check(
        "country annex narrowed to a state: Munich annex tagged DE-BY",
        annex["jurisdiction_code"] == "DE-BY",
    )
    gl = await demo.req("GET", f"/versions/{published['global-leave']}/sections")
    refs = [r for s in gl for r in s["refs"]]
    demo.check(
        "cross-reference resolved: Global leave → Annex A",
        any(r["target_text"] == "Annex A" and r["to_section_id"] for r in refs),
    )
    model = get_settings().embedding_model_key
    embeddings = [
        (await demo.req("GET", f"/versions/{vid}"))["parse_report"].get("embedding", {})
        for vid in [*published.values(), v2]
    ]
    demo.check(
        f"every published version is indexed with {model}",
        all(e.get("model") == model for e in embeddings),
    )
    demo.check(
        "coverage: DE has leave and sick pay; US-CA has sick pay and payroll",
        all(
            cells.get(k)
            for k in [
                ("DE", "leave"),
                ("DE", "sick_pay"),
                ("US-CA", "sick_pay"),
                ("US-CA", "payroll"),
            ]
        ),
    )
    demo.check(
        "coverage gaps stay visible: no sick-pay policy for FR or ES",
        not cells.get(("FR", "sick_pay")) and not cells.get(("ES", "sick_pay")),
    )
    outsider = headers(OUTSIDER)
    await demo.client.get("/v1/me", headers=outsider)
    r = await demo.client.get(f"/v1/workspaces/{demo.ws}/documents", headers=outsider)
    r2 = await demo.client.get(
        f"/v1/workspaces/{demo.ws}/versions/{published['de-leave']}", headers=outsider
    )
    demo.check(
        "another tenant can't see Northwind's documents or versions",
        r.status_code == 404 and r2.status_code == 404,
    )


async def run(api_url: str | None, workspace_name: str = WORKSPACE) -> int:
    if api_url:
        client = httpx.AsyncClient(base_url=api_url.rstrip("/"), timeout=60)
    else:
        from app.main import create_app

        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://demo", timeout=60
        )
    try:
        async with client:
            demo = Demo(client, poll=True, workspace_name=workspace_name)
            settings = get_settings()
            print(
                f"M2 demo against {api_url or 'in-process app (jobs inline)'}; parser="
                f"{settings.parser_provider}, embeddings={settings.embedding_model_key}, "
                f"llm={settings.llm_provider}\n"
            )
            await demo.client.get("/v1/me", headers=demo.h)
            await setup_workspace(demo)
            topics = {t["key"]: t["id"] for t in await demo.req("GET", "/topics")}
            print("\nIngesting seed/northwind/")
            published: dict[str, str] = {}
            for doc in DOCS:
                published[doc.key] = await ingest(demo, doc, topics, published)
            v2 = await midyear_change(demo, published)
            cells = await print_coverage(demo)
            await checks(demo, published, v2, cells)
    finally:
        if not api_url:
            from app.core.db import get_engine

            await get_engine().dispose()
    print()
    if demo.failures:
        print(f"FAILED: {demo.failures} check(s) failed")
        return 1
    print("All checks passed: the Northwind knowledge base is ingested, reviewed and published.")
    return 0


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", help="talk to a running API (with a worker) instead")
    parser.add_argument("--workspace", default=WORKSPACE, help="workspace name to create/reuse")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.api_url, args.workspace)))


if __name__ == "__main__":
    main()
