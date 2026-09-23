"""Domain-neutral ResearchNeed normalization seam. Adapters implement this."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.services.research.followup import FollowUpNeedDraft
from app.services.research.models import ResearchPlan
from app.services.research.planner import ResearchNeedDraft


class ResearchNeedNormalizer(Protocol):
    """Rewrite or split generated needs before retrieval. Must not retrieve."""

    async def normalize_drafts(
        self, drafts: Sequence[ResearchNeedDraft]
    ) -> list[ResearchNeedDraft]: ...

    async def normalize_follow_up_drafts(
        self, drafts: Sequence[FollowUpNeedDraft]
    ) -> list[FollowUpNeedDraft]: ...

    async def normalize_plan(self, plan: ResearchPlan) -> ResearchPlan: ...


class NoOpNeedNormalizer:
    """Identity normalizer. Used when no domain adapter is injected."""

    async def normalize_drafts(
        self, drafts: Sequence[ResearchNeedDraft]
    ) -> list[ResearchNeedDraft]:
        return list(drafts)

    async def normalize_follow_up_drafts(
        self, drafts: Sequence[FollowUpNeedDraft]
    ) -> list[FollowUpNeedDraft]:
        return list(drafts)

    async def normalize_plan(self, plan: ResearchPlan) -> ResearchPlan:
        return plan
