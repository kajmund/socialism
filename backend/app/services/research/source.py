"""ResearchSource contract. Concrete adapters live in sibling modules."""

from __future__ import annotations

from typing import Protocol

from app.services.research.models import (
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
    ResearchSourceType,
)


class ResearchSource(Protocol):
    source_type: ResearchSourceType

    async def research(
        self,
        need: ResearchNeed,
        context: ResearchContext,
    ) -> list[ResearchEvidence]: ...
