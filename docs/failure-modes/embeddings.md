# Failure modes: embeddings

Scope: embedding chunks with Vertex AI `gemini-embedding-001` at 768
dimensions (EU), behind the `embeddings` interface; storing them in
`chunk_embeddings` with model and dims on every row (PLAN §4.6, ADR-0006).

The invariant: **every stored vector says which model and size produced it,
and a search only ever compares vectors from the same model.**

| # | How it fails | How we detect it | What the system does instead | Test that proves it |
|---|--------------|------------------|------------------------------|---------------------|
| 1 | The provider returns a vector of the wrong size (e.g. 3072 when 768 was asked) | Length check in the provider, plus a DB `CHECK (vector_dims(embedding) = dims)` | Error → retry → job failure; never stored | `test_embeddings.py::test_wrong_dimension_is_rejected`, `test_constraints.py::test_db_rejects_dimension_mismatch` |
| 2 | Vectors from two models are compared | `model` and `dims` on every row; one partial HNSW index per model | Search filters by the workspace's `active_embedding_model` (M3); the schema keeps models apart | `test_embeddings.py::test_embeddings_store_model_and_dims` |
| 3 | Switching models leaves the workspace half on the new one | Coverage of the new model over current chunks | `active_embedding_model` can only switch once every chunk of every published version has an embedding for the new model | `test_embeddings.py::test_cannot_activate_incomplete_model` |
| 4 | Reduced-dimension vectors aren't unit length, so cosine/dot scores drift | Norm check | The provider L2-normalises every vector | `test_embeddings.py::test_vectors_are_l2_normalised` |
| 5 | 429s, timeouts and transient errors fail whole versions | Typed provider errors | Retries with exponential backoff and jitter, plus bounded concurrency; only the final failure fails the task (→ `job_failures`) | `test_embeddings.py::test_transient_errors_are_retried` |
| 6 | Text over the model's 2,048-token limit is silently truncated | Token estimate of header + chunk text | Chunks are capped far below the limit. Anything over `EMBED_MAX_TOKENS` is rejected, not truncated | `test_embeddings.py::test_overlong_input_is_rejected` |
| 7 | Unchanged chunks are re-embedded on every new version (cost) | `content_hash` of exactly the embedded text (header + chunk) | Embeddings are reused across versions of the same document when hash and model match | `test_pipeline.py::test_unchanged_chunks_reuse_embeddings` |
| 8 | Documents and queries are embedded the same way, so retrieval is weaker | — | The interface takes an `input_type`: `document` for chunks (RETRIEVAL_DOCUMENT), `query` for searches (M3) | `test_embeddings.py::test_input_type_reaches_provider` |
| 9 | A version is marked ready with some chunks missing embeddings | Count check before `ready` | The version stays in `embedding` until every chunk has an active-model embedding | `test_pipeline.py::test_ready_only_when_fully_embedded` |
| 10 | Policy text is processed outside the EU | Settings | Vertex location must be an EU region outside local/test (ADR-0006) | `test_config.py::test_vertex_location_must_be_eu` |
| 11 | The fake embedder runs in a real environment | Settings | Fake providers are refused unless `ENVIRONMENT` is local/test (ADR-0004 rule 4) | `test_config.py::test_fake_providers_refused_outside_local` |
