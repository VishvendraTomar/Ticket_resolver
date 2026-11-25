"""The jurisdiction tree in memory (318 static reference rows, loaded once per process)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models import Jurisdiction, JurisdictionLevel


@dataclass(frozen=True)
class JurisdictionTree:
    parents: dict[str, str | None]
    names: dict[str, str]
    levels: dict[str, JurisdictionLevel]

    def __contains__(self, code: object) -> bool:
        return code in self.parents

    def chain(self, code: str) -> list[str]:
        """The code and its ancestors, most specific first: DE-BY → DE → EU → GLOBAL."""
        out: list[str] = []
        current: str | None = code
        while current is not None:
            out.append(current)
            current = self.parents[current]
        return out

    def is_within(self, code: str, ancestor: str) -> bool:
        return ancestor in self.chain(code)

    def overlaps(self, a: str, b: str) -> bool:
        """True when one applies inside the other (same, ancestor or descendant)."""
        return self.is_within(a, b) or self.is_within(b, a)

    def label(self, code: str) -> str:
        return f"{self.names[code]} ({code})"


_TREE: JurisdictionTree | None = None


async def load_tree(session: AsyncSession) -> JurisdictionTree:
    global _TREE
    if _TREE is None:
        rows = (await session.execute(select(Jurisdiction))).scalars().all()
        _TREE = JurisdictionTree(
            parents={r.code: r.parent_code for r in rows},
            names={r.code: r.name for r in rows},
            levels={r.code: r.level for r in rows},
        )
    return _TREE
