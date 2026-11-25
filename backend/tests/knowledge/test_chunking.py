"""docs/failure-modes/parsing.md — sectioning, chunking, references, headers."""

from __future__ import annotations

from datetime import date

from app.core.tokens import estimate_tokens
from app.ingestion.chunking import TARGET_MAX, chunk_section
from app.ingestion.header import content_hash, context_header, ts_config
from app.ingestion.refs import extract_refs, resolve_ref
from app.ingestion.sectioning import MAX_PARENT_TOKENS, build_sections, clause_number
from app.providers.parser.base import Block, BlockKind
from app.providers.parser.fake import parse_markdown


def sentence(i: int) -> str:
    return f"Employees accrue leave under rule {i} which applies to every eligible worker here."


def big_table(rows: int) -> str:
    lines = ["| Years of service | Days | Notes |", "|---|---|---|"]
    lines += [f"| {i} | {20 + i} | extra day after year {i} of service |" for i in range(rows)]
    return "\n".join(lines)


def test_tables_are_never_split() -> None:
    md = "# P\n\n## 1. Leave\n\n" + "\n\n".join(sentence(i) for i in range(30))
    md += "\n\n" + big_table(60) + "\n\n" + "\n\n".join(sentence(i) for i in range(30, 40))
    sectioned = build_sections(parse_markdown(md))
    all_chunks = [c for s in sectioned.sections for c in chunk_section(s)[0]]
    tables = [c for c in all_chunks if "| Years of service |" in c.text]
    assert len(tables) == 1, "the table must sit in exactly one chunk"
    assert tables[0].text.count("extra day after year") == 60
    _, warnings = chunk_section(next(s for s in sectioned.sections if s.has_table))
    assert any("kept as one chunk" in w for w in warnings)


def test_numbered_clause_is_not_split() -> None:
    clause = "4.2 " + " ".join(sentence(i) for i in range(60))
    lead_in = "4.3 Carry-over is allowed as follows:"
    items = "\n".join(f"- condition {i} for carrying over unused days" for i in range(5))
    md = f"# P\n\n## 4. Leave\n\n{clause}\n\n{lead_in}\n{items}\n"
    [section] = build_sections(parse_markdown(md)).sections
    chunks, _ = chunk_section(section)
    long_pieces = [c for c in chunks if "Employees accrue leave" in c.text]
    assert len(long_pieces) > 1, "a long clause is split at sentences"
    assert long_pieces[0].text.startswith("4.2 ")
    assert all(c.text.startswith("4.2 (continued)") for c in long_pieces[1:])
    with_lead_in = [c for c in chunks if lead_in in c.text]
    assert len(with_lead_in) == 1
    assert with_lead_in[0].text.count("- condition") == 5, "lead-in and its list stay together"


def test_flat_document_gets_fallback_sections() -> None:
    blocks = [Block(BlockKind.PARAGRAPH, sentence(i)) for i in range(200)]
    sectioned = build_sections(blocks)
    assert len(sectioned.sections) > 1
    assert all(s.title and s.title.startswith("Part ") for s in sectioned.sections)
    assert "no headings detected" in sectioned.warnings[0]


def test_size_bounds() -> None:
    md = "# Handbook\n\n## 1. Everything\n\n" + "\n\n".join(sentence(i) for i in range(400))
    sectioned = build_sections(parse_markdown(md))
    assert len(sectioned.sections) > 1
    assert all(s.token_count <= MAX_PARENT_TOKENS for s in sectioned.sections)
    chunks = [c for s in sectioned.sections for c in chunk_section(s)[0]]
    assert all(c.token_count <= TARGET_MAX for c in chunks)
    assert sum(c.token_count >= 150 for c in chunks) >= len(chunks) - len(sectioned.sections)


def test_heading_paths_and_clause_numbers() -> None:
    md = (
        "# Northwind Leave Policy\n\n## Germany\n\n### 4. Annual leave\n\nText A.\n\n"
        "#### 4.2 Carry-over\n\nText B.\n\n## Annex B\n\nText C.\n"
    )
    sectioned = build_sections(parse_markdown(md))
    assert sectioned.title == "Northwind Leave Policy"
    assert [(s.heading_path, s.clause_number) for s in sectioned.sections] == [
        (["Germany", "4. Annual leave"], "4"),
        (["Germany", "4. Annual leave", "4.2 Carry-over"], "4.2"),
        (["Annex B"], "Annex B"),
    ]
    assert clause_number("§ 12 Notice") == "12"
    assert clause_number("Article 7a. Pay") == "7a"
    assert clause_number("appendix 2 forms") == "Appendix 2"
    assert clause_number("Overtime") is None


def test_cross_references_are_extracted_and_resolved() -> None:
    md = (
        "# P\n\n## 4.2 Carry-over\n\nSee Annex B and section 5.1; also § 9 (not in this "
        "document).\n\n## 5.1 Payout\n\nText.\n\n## Annex B\n\nForms.\n"
    )
    sections = build_sections(parse_markdown(md)).sections
    refs = extract_refs(sections[0].text)
    assert refs == ["Annex B", "5.1", "9"]
    assert [resolve_ref(r, sections, exclude=0) for r in refs] == [2, 1, None]


def test_context_header() -> None:
    header = context_header(
        document_title="Northwind Leave Policy",
        heading_path=["Germany", "4.2 Annual leave"],
        jurisdiction="Germany (DE)",
        scope={"worker_type": "employee", "entity": "*"},
        effective_from=date(2026, 1, 1),
        effective_to=None,
    )
    assert header == (
        "Northwind Leave Policy › Germany › 4.2 Annual leave — applies to: Germany (DE), "
        "worker_type: employee — valid from 2026-01-01"
    )
    assert content_hash(header, "x") != content_hash(header, "y")
    assert content_hash(header, "x") == content_hash(header, "x")
    assert estimate_tokens(header) < 60


def test_ts_config_by_language() -> None:
    assert ts_config("de-DE") == "german"
    assert ts_config("en") == "english"
    assert ts_config("hi") == "simple"
