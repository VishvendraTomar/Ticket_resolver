"""Blocks → sections (parent units). docs/failure-modes/parsing.md #2, #6, #7.

A section is the content under one heading, with its full heading path and
clause number. Sections over the parent cap are split at block boundaries
(tables and clauses stay whole). Documents without headings get fallback
sections of paragraph groups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.tokens import estimate_tokens
from app.providers.parser.base import Block, BlockKind

MAX_PARENT_TOKENS = 1500
FALLBACK_SECTION_TOKENS = 800

# "4", "4.2", "4.2.1a", "§ 12", "Article 7", "Section 3.1", "Annex B", "Appendix 2".
_CLAUSE = re.compile(
    r"^\s*(?:(?:§|art(?:icle|\.)?|section|clause)\s*)?(\d+(?:\.\d+)*[a-z]?)[.)]?(?=\s|$)"
    r"|^\s*((?:annex|appendix|schedule)\s+[A-Z0-9]+)\b",
    re.IGNORECASE,
)


def clause_number(text: str) -> str | None:
    match = _CLAUSE.match(text)
    if not match:
        return None
    if match.group(1):
        return match.group(1)
    words = match.group(2).split()
    return f"{words[0].capitalize()} {words[1].upper()}"


def block_text(block: Block) -> str:
    return f"- {block.text}" if block.kind is BlockKind.LIST_ITEM else block.text


@dataclass
class SectionDraft:
    heading_path: list[str]
    title: str | None
    clause_number: str | None
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(block_text(b) for b in self.blocks)

    @property
    def token_count(self) -> int:
        return estimate_tokens(self.text)

    @property
    def has_table(self) -> bool:
        return any(b.kind is BlockKind.TABLE for b in self.blocks)

    @property
    def page_start(self) -> int | None:
        return next((b.page for b in self.blocks if b.page is not None), None)


@dataclass(frozen=True)
class Sectioned:
    title: str | None  # document title (level-0 heading), if any
    sections: list[SectionDraft]
    warnings: list[str]


def build_sections(blocks: list[Block], max_parent_tokens: int = MAX_PARENT_TOKENS) -> Sectioned:
    title: str | None = None
    warnings: list[str] = []
    headings = [b for b in blocks if b.kind is BlockKind.HEADING and (b.level or 0) >= 1]

    if not headings:
        content = [b for b in blocks if b.kind is not BlockKind.HEADING]
        title = next((b.text for b in blocks if b.kind is BlockKind.HEADING), None)
        warnings.append("no headings detected: sections are paragraph groups")
        sections = _fallback_sections(content)
    else:
        stack: list[tuple[int, str]] = []  # (level, heading text)
        sections = []
        current = SectionDraft(heading_path=[], title=None, clause_number=None)
        for block in blocks:
            if block.kind is BlockKind.HEADING:
                level = block.level or 0
                if level == 0:
                    title = title or block.text
                    continue
                if current.blocks:
                    sections.append(current)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, block.text))
                current = SectionDraft(
                    heading_path=[text for _, text in stack],
                    title=block.text,
                    clause_number=clause_number(block.text),
                )
            else:
                current.blocks.append(block)
        if current.blocks:
            sections.append(current)

    capped: list[SectionDraft] = []
    for section in sections:
        capped.extend(_cap(section, max_parent_tokens, warnings))
    return Sectioned(title=title, sections=capped, warnings=warnings)


def _fallback_sections(content: list[Block]) -> list[SectionDraft]:
    sections: list[SectionDraft] = []
    current = SectionDraft(heading_path=[], title="Part 1", clause_number=None)
    for block in content:
        if current.blocks and current.token_count + estimate_tokens(block.text) > (
            FALLBACK_SECTION_TOKENS
        ):
            sections.append(current)
            current = SectionDraft(
                heading_path=[], title=f"Part {len(sections) + 1}", clause_number=None
            )
        current.blocks.append(block)
    if current.blocks:
        sections.append(current)
    return sections


def _cap(section: SectionDraft, limit: int, warnings: list[str]) -> list[SectionDraft]:
    if section.token_count <= limit:
        return [section]
    parts: list[SectionDraft] = []
    current = SectionDraft(section.heading_path, section.title, section.clause_number)
    for block in section.blocks:
        tokens = estimate_tokens(block_text(block))
        if current.blocks and current.token_count + tokens > limit:
            parts.append(current)
            current = SectionDraft(section.heading_path, section.title, section.clause_number)
        current.blocks.append(block)
        if tokens > limit:
            warnings.append(
                f"a {block.kind} of ~{tokens} tokens under '{section.title}' exceeds the "
                f"{limit}-token section cap and was kept whole"
            )
    parts.append(current)
    for i, part in enumerate(parts[1:], start=2):
        part.title = f"{section.title or 'Section'} (part {i})"
    return parts
