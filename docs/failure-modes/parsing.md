# Failure modes: parsing, sectioning and chunking

Scope: turning an uploaded file into sections (parent units) and chunks.
Docling runs in the ingestion worker behind the `parser` interface
(ADR-0004, ADR-0006). Sectioning and chunking are our own deterministic code.

The invariant: **a chunk is a faithful, self-describing slice of one clause:
never half a table, never half a numbered clause, never without its heading
path.**

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 1 | A table is split across chunks, or flattened into unreadable text | Parser emits tables as Markdown blocks | The chunker treats a table as one unit. An oversized table becomes its own chunk, with a warning in the parse report | `test_chunking.py::test_tables_are_never_split` |
| 2 | A numbered clause ("4.2 …") is cut in the middle, or loses its number | Clause numbers detected on headings and paragraph starts | Chunk boundaries fall only between clauses or paragraphs. A clause over the limit is split at sentence boundaries, and each piece keeps the clause number | `test_chunking.py::test_numbered_clause_is_not_split` |
| 3 | A scanned PDF has no text layer | Docling OCR, with per-page confidence | Text is OCR'd. Pages below `OCR_MIN_CONFIDENCE` are listed in the parse report, and the version is flagged `needs_review` | `test_parsing.py::test_low_ocr_confidence_flags_review`; `test_docling.py::test_scanned_pdf_is_ocrd` (docling-marked) |
| 4 | The parser returns almost nothing (encrypted PDF, image-only, empty file) | Extracted-text length vs. file size and page count | Version fails with "no text extracted", shown to the editor; nothing is indexed | `test_parsing.py::test_empty_parse_fails_with_reason` |
| 5 | The parser hangs or explodes on a huge or hostile file | Page limit (`MAX_PAGES`) and a hard time limit on the task | The task is killed, recorded in `job_failures`, and the version is failed | `test_parsing.py::test_page_limit_fails_version` |
| 6 | No headings detected (flat text), so sections are meaningless | Parse report counts headings | Fallback: sections are cut by paragraph groups under the size cap; the report warns "no headings detected" | `test_chunking.py::test_flat_document_gets_fallback_sections` |
| 7 | A section is huge (a whole chapter) and swamps the answer context | Token estimate per section | Parents are capped at ~1,500 tokens (split at paragraph boundaries); chunks target 300–500 | `test_chunking.py::test_size_bounds` |
| 8 | A cross-reference ("see Annex B", "§4.2") is lost, so retrieval can't follow it | Reference patterns in section text | Stored in `section_refs` and resolved to the target section when it exists. Unresolved references keep the target text | `test_chunking.py::test_cross_references_are_extracted_and_resolved` |
| 9 | A country annex inside a global handbook inherits the wrong jurisdiction (PLAN §4.2) | Sections carry their own optional jurisdiction/scope/topic | Chunks take the section's values when set, else the version's | `test_versions.py::test_section_tags_override_version_defaults` |
| 10 | A chunk is embedded without saying where it applies | — | A context header ("Doc › heading path › clause — applies to: DE, employees — valid from 2026-01-01") is built **after** tags are confirmed, and is part of the embedded text | `test_chunking.py::test_context_header` |
| 11 | Re-parsing with a new Docling version silently changes the output | Parser name and version stored in the parse report | Visible per version; content hashes show what changed | `test_parsing.py::test_parse_report_records_parser` |
| 12 | Text inside documents contains instructions ("ignore previous instructions…") | — | Document text is data. Parsing never interprets it; prompts wrap and label it ([tagging](tagging.md) #4) | — (see tagging) |

## Not covered yet
- Layout-heavy PDFs (multi-column, footnotes) are parsed by Docling's layout
  model; quality is judged with the parse report and section preview, and
  measured on the golden set in M3.
