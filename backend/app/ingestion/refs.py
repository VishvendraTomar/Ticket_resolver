"""Cross-references between sections. docs/failure-modes/parsing.md #8."""

from __future__ import annotations

import re

from app.ingestion.sectioning import SectionDraft

_REF = re.compile(
    r"\b(?:see|under|per|in accordance with|as set out in|refer to)\s+"
    r"(?:(?:section|clause|article|paragraph)\s+|§\s*)?"
    r"((?:annex|appendix|schedule)\s+[A-Z0-9]+|\d+(?:\.\d+)*[a-z]?)"
    r"|§\s*(\d+(?:\.\d+)*[a-z]?)"
    r"|\b(?:section|clause|article|paragraph)\s+(\d+(?:\.\d+)*[a-z]?)\b"
    r"|\b((?:annex|appendix|schedule)\s+[A-Z0-9]+)\b",
    re.IGNORECASE,
)


def _normalise(target: str) -> str:
    words = target.split()
    if len(words) == 2 and not words[0][0].isdigit():
        return f"{words[0].capitalize()} {words[1].upper()}"
    return target.strip()


def extract_refs(text: str) -> list[str]:
    """Targets mentioned in the text, in order, deduplicated (e.g. "4.2", "Annex B")."""
    found: list[str] = []
    for match in _REF.finditer(text):
        target = _normalise(next(g for g in match.groups() if g))
        if target not in found:
            found.append(target)
    return found


def resolve_ref(target: str, sections: list[SectionDraft], exclude: int) -> int | None:
    """Index of the section the target points to, or None if it isn't in this document."""
    for i, section in enumerate(sections):
        if i != exclude and section.clause_number == target:
            return i
    return None
