"""Sections → chunks of ~300–500 tokens. docs/failure-modes/parsing.md #1, #2, #7.

Chunk boundaries fall only between blocks, so a table or a numbered clause is
never cut. A single block over the limit stays whole if it's a table (flagged),
or is split at sentence boundaries with the clause number repeated on each
piece.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.tokens import estimate_tokens
from app.ingestion.sectioning import SectionDraft, block_text, clause_number
from app.providers.parser.base import BlockKind

TARGET_MIN = 300
TARGET_MAX = 500
# Oversized tables become one chunk; anything beyond this is refused upstream.
HARD_MAX = 1200

_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z0-9(§\"'])")


@dataclass(frozen=True)
class ChunkDraft:
    text: str
    token_count: int


def chunk_section(
    section: SectionDraft, target_min: int = TARGET_MIN, target_max: int = TARGET_MAX
) -> tuple[list[ChunkDraft], list[str]]:
    warnings: list[str] = []
    pieces: list[str] = []
    for kind, text in _units(section):
        tokens = estimate_tokens(text)
        if tokens <= target_max:
            pieces.append(text)
        elif kind is BlockKind.TABLE:
            pieces.append(text)
            warnings.append(
                f"table of ~{tokens} tokens in '{section.title}' kept as one chunk"
                + (" (over the hard limit)" if tokens > HARD_MAX else "")
            )
        else:
            pieces.extend(_split_sentences(text, target_max))

    chunks: list[ChunkDraft] = []
    current: list[str] = []
    current_tokens = 0
    for piece in pieces:
        tokens = estimate_tokens(piece)
        if current and current_tokens + tokens > target_max:
            chunks.append(_draft(current))
            current, current_tokens = [], 0
        current.append(piece)
        current_tokens += tokens
    if current:
        # Merge a short tail into the previous chunk when the result still fits the target.
        if chunks and current_tokens < target_min // 2:
            merged = chunks[-1].text + "\n\n" + "\n\n".join(current)
            if estimate_tokens(merged) <= target_max and not _has_table(current):
                chunks[-1] = ChunkDraft(merged, estimate_tokens(merged))
                return chunks, warnings
        chunks.append(_draft(current))
    return chunks, warnings


def _units(section: SectionDraft) -> list[tuple[BlockKind, str]]:
    """Blocks, with a lead-in ("… as follows:") kept together with its list items."""
    units: list[tuple[BlockKind, str]] = []
    for block in section.blocks:
        text = block_text(block)
        if (
            block.kind is BlockKind.LIST_ITEM
            and units
            and (units[-1][1].rstrip().endswith(":") or units[-1][0] is BlockKind.LIST_ITEM)
            and units[-1][0] is not BlockKind.TABLE
        ):
            units[-1] = (BlockKind.LIST_ITEM, units[-1][1] + "\n" + text)
        else:
            units.append((block.kind, text))
    return units


def _has_table(pieces: list[str]) -> bool:
    return any(p.lstrip().startswith("|") for p in pieces)


def _draft(pieces: list[str]) -> ChunkDraft:
    text = "\n\n".join(pieces)
    return ChunkDraft(text=text, token_count=estimate_tokens(text))


def _split_sentences(text: str, limit: int) -> list[str]:
    number = clause_number(text)
    sentences = _SENTENCE_END.split(text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and estimate_tokens(candidate) > limit:
            parts.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        parts.append(current)
    if number:
        # Every piece of a long clause still says which clause it belongs to.
        parts = [parts[0]] + [f"{number} (continued) {p}" for p in parts[1:]]
    return parts
