"""Context headers: what every chunk says about itself. docs/failure-modes/parsing.md #10.

Built after tags are confirmed (the header depends on them) and embedded with
the chunk text, so retrieval and the model both see where a rule applies.
"""

from __future__ import annotations

import hashlib
from datetime import date


def context_header(
    *,
    document_title: str,
    heading_path: list[str],
    jurisdiction: str | None,
    scope: dict[str, str],
    effective_from: date | None,
    effective_to: date | None,
) -> str:
    path = " › ".join([document_title, *heading_path])
    applies = [jurisdiction or "jurisdiction not set"]
    applies += [f"{k}: {v}" for k, v in sorted(scope.items()) if v != "*"]
    valid = f"valid from {effective_from.isoformat()}" if effective_from else "validity not set"
    if effective_to:
        valid += f" until {effective_to.isoformat()}"
    return f"{path} — applies to: {', '.join(applies)} — {valid}"


def embedded_text(header: str, text: str) -> str:
    return f"{header}\n\n{text}"


def content_hash(header: str, text: str) -> str:
    """Hash of exactly what gets embedded (reuse key, embeddings.md #7)."""
    return hashlib.sha256(embedded_text(header, text).encode()).hexdigest()


# Postgres text-search configuration per document language (BCP 47 primary tag).
TS_CONFIGS = {
    "da": "danish", "de": "german", "en": "english", "es": "spanish", "fi": "finnish",
    "fr": "french", "hu": "hungarian", "it": "italian", "nl": "dutch", "no": "norwegian",
    "pt": "portuguese", "ro": "romanian", "ru": "russian", "sv": "swedish", "tr": "turkish",
}  # fmt: skip


def ts_config(language: str) -> str:
    return TS_CONFIGS.get(language.split("-")[0].lower(), "simple")
