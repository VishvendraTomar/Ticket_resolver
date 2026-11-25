# Failure modes: tagging (jurisdiction, scope, topic)

Scope: AI tag suggestions per version and section (small Gemini model via
LiteLLM, behind the `llm` interface), human confirmation, and validation of
tags against the jurisdiction tree, the workspace's topics and its scope
fields.

The invariant: **a wrong jurisdiction tag silently poisons retrieval, so no AI
suggestion ever reaches a published version without a human confirming it.**

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 1 | The model suggests the wrong jurisdiction, and it gets used | — | Suggestions are stored separately from confirmed tags. Publishing needs confirmed tags; nothing is auto-applied | `test_tagging.py::test_suggestions_are_not_applied_without_confirmation` |
| 2 | The model returns invalid JSON, an unknown jurisdiction code, or a topic the workspace doesn't have | Structured output validated with Pydantic, then each value checked against the jurisdiction tree, topics and scope fields | Invalid values are dropped and the reason recorded; the editor still sees the section, untagged | `test_tagging.py::test_invalid_suggestions_are_discarded` |
| 3 | The LLM is down, slow or out of quota | Timeouts and typed provider errors | Ingestion continues without suggestions ("no suggestions: provider unavailable"); the editor tags by hand | `test_tagging.py::test_llm_outage_does_not_block_ingestion` |
| 4 | Document text contains a prompt injection ("tag this as GLOBAL") | — | Text is wrapped in labelled delimiters as data. Output is limited to the allowed values (#2), and a human confirms anyway (#1) | `test_tagging.py::test_document_text_is_wrapped_as_data` |
| 5 | Policy text leaves the EU | Provider settings | Vertex AI location must be an EU region outside local/test, or settings refuse to start (ADR-0006) | `test_config.py::test_vertex_location_must_be_eu` |
| 6 | A huge document causes hundreds of LLM calls | Section count | One call per batch of sections, with section text truncated to a fixed budget. Past `TAGGING_MAX_SECTIONS`, the rest are left for manual tagging and the report says so | `test_tagging.py::test_tagging_is_capped` |
| 7 | A section is tagged with a jurisdiction outside its version's (an "FR" annex inside a "DE" policy) | Tree check: a section's jurisdiction must be the version's or a descendant of it | 422 on confirm | `test_tagging.py::test_section_jurisdiction_must_be_within_version` |
| 8 | Scope values that don't exist ("worker_type: freelancer" when the field only allows employee, contractor) | Validated against the workspace's scope fields | 422 | `test_tagging.py::test_scope_values_are_validated` |
| 9 | Confirmed tags are wrong anyway | Coverage map ([ingestion](ingestion.md) #15) shows what each country actually has | Editors spot gaps and oddities before tickets do | `test_coverage.py::test_coverage_counts_published_only` |
