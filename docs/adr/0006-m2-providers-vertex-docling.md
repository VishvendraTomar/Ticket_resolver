# ADR-0006: M2 providers — Vertex AI (EU) embeddings and LLM, Docling parser

- Status: Accepted
- Date: 2026-11-25
- Decides: PLAN §5 #2 (embeddings) and #3 (small LLM); parser for M2
- Builds on: ADR-0004 (every provider behind an interface with a fake)

## Decisions (from the product owner, 2026-11-25)
1. **Embeddings:** Vertex AI `gemini-embedding-001` at **768 dimensions**,
   EU region, behind the `embeddings` interface. Model and dims are stored on
   every embedding.
2. **LLMs:** Vertex AI through LiteLLM, EU region. Small model = the newest
   Gemini Flash available in-region. The strong model is decided in M4.
3. **Parser:** Docling for PDF, DOCX, HTML and Markdown, with OCR, run inside
   the ingestion worker.
4. **Live calls** only in `@pytest.mark.live` tests; fakes everywhere else.

## Residency findings (Google's data-residency page, checked 2026-11-25)
Source: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/data-residency

- `gemini-embedding-001`: ML processing is listed for the **EU multi-region
  only**, with no in-country processing in Frankfurt (europe-west3) or the
  Netherlands (europe-west4). The page notes the model doesn't accept the
  `eu` multi-region endpoint, but calls to EU single-region endpoints such
  as europe-west4 are processed within the EU. **So data stays in the EU,
  but not necessarily in one country.**
- Gemini Flash, in-country in europe-west3 (Frankfurt): `gemini-3.5-flash`
  and `gemini-2.5-flash` (128k). Newer Flash models (`gemini-3.6/3.7/3.8-flash`)
  are listed for the EU multi-region only (the `eu` endpoint). Nothing is
  processed in-country in europe-west4.
- The **global endpoint gives no residency guarantee** and must never be used.
- 768 is one of Google's recommended output sizes (3072, 1536, 768;
  Matryoshka). Vertex accepts one input per embedding request. Inputs are
  limited to 2,048 tokens and silently truncated beyond that.

## Configuration chosen
| Setting | Default | Why |
|---------|---------|-----|
| `EMBEDDINGS_PROVIDER` | `vertex` (`fake` in local/test) | — |
| `EMBEDDINGS_MODEL` / `EMBEDDINGS_DIMS` | `gemini-embedding-001` / `768` | Decision 1 |
| `EMBEDDINGS_LOCATION` | `europe-west4` | Named in Google's note as processed within the EU |
| `LLM_PROVIDER` | `vertex` (`fake` in local/test) | — |
| `LLM_SMALL_MODEL` | `vertex_ai/gemini-3.5-flash` | Newest Flash with **in-country** (Frankfurt) processing |
| `LLM_LOCATION` | `europe-west3` | In-region, as asked |
| `PARSER_PROVIDER` | `docling` (`fake` in unit tests) | Decision 3 |

`gemini-3.8-flash` is newer but EU-multi-region-only. Switching to it is a
config change (`LLM_SMALL_MODEL=vertex_ai/gemini-3.8-flash`,
`LLM_LOCATION=eu`), if EU-wide processing is acceptable. That's for the
product owner to decide; see PROGRESS "Decisions made — review".

Guardrails in settings, outside `ENVIRONMENT=local/test`:
- Vertex locations must be EU (`europe-*` or `eu`); `global` and non-EU
  regions are refused at startup.
- Fake providers are refused (ADR-0004 rule 4).

## Implementation notes
- **Embeddings** call Vertex through LiteLLM (`vertex_ai/gemini-embedding-001`,
  `dimensions=768`, task type `RETRIEVAL_DOCUMENT` or `RETRIEVAL_QUERY`). We
  L2-normalise, because only full-size vectors come normalised. Requests are
  concurrent, one text each, with bounded concurrency and retries. Inputs
  are checked against a token budget; we reject rather than truncate.
- The stored model key is `vertex/gemini-embedding-001@768`: provider, model
  and dims. A future model gets new rows, not new columns (PLAN §4.6).
- **Docling** runs in the worker process. Markdown, HTML and DOCX use its
  non-ML backends. PDF uses its layout model plus OCR, and the models are
  downloaded once into the worker's cache. Torch is installed CPU-only.
- Credentials: Application Default Credentials (`GOOGLE_APPLICATION_CREDENTIALS`
  or workload identity), plus `VERTEX_PROJECT`. No keys in code.

## Consequences
- Fully offline test suite. Live tests need `VERTEX_PROJECT` and ADC.
- If strict in-country (Germany-only) processing becomes a requirement,
  `gemini-embedding-001` can't meet it today. `text-multilingual-embedding-002`
  is listed in-country for Frankfurt, at the cost of re-embedding everything
  (the schema already supports it).
- Docling + torch make the worker image large (~1–2 GB). The API image
  doesn't need them, but M2 uses one image for both; splitting is a later
  optimisation.
