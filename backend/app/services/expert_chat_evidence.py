"""Read-only reusable research evidence for expert chat."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import EvidenceSet, ExecutionAttempt
from app.services.knowledge.models import KnowledgeScope
from app.services.prompt_catalog import render_prompt
from app.services.research.composition import build_standard_question_graph
from app.services.research.models import (
    RESEARCH_SOURCE_TYPES,
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
)
from app.services.research.question_reuse import safe_lookup_reusable_evidence


def _render_evidence(items: Sequence[ResearchEvidence]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(
        (candidate for candidate in items if candidate.status == "found"),
        start=1,
    ):
        reuse = item.metadata.get("reuse")
        freshness = reuse.get("freshness") if isinstance(reuse, dict) else "unknown"
        lines = [f"[R{index}] {item.title or item.source_type}"]
        lines.append(f"Källtyp: {item.source_type}")
        lines.append(f"Aktualitet: {freshness}")
        if item.locator:
            lines.append(f"Plats: {item.locator}")
        if item.excerpt:
            lines.append(f'Utdrag: "{item.excerpt}"')
        if item.source_url and item.source_url.startswith(("http://", "https://")):
            lines.append(f"URL: {item.source_url}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def reusable_expert_chat_evidence_context(
    session: AsyncSession,
    *,
    customer_id: int,
    question: str,
    prompts: dict[str, str],
) -> str:
    """Return prompt context from existing Question→Evidence links only.

    This path never creates a Run, Attempt, question, or provider request.
    Case-scoped evidence is excluded because library chat has no document case.
    """
    reused = await safe_lookup_reusable_evidence(
        session,
        graph=build_standard_question_graph(),
        need=ResearchNeed(
            id="expert_chat_reuse",
            question=question,
            why_needed="",
            source_types=list(RESEARCH_SOURCE_TYPES),
        ),
        context=ResearchContext(scope=KnowledgeScope(customer_id=customer_id)),
    )
    attempt_ids = {
        str(candidate.metadata.get("source_attempt_id"))
        for candidate in reused
        if candidate.metadata.get("source_attempt_id")
    }
    frozen_attempt_ids: set[str] = set()
    if attempt_ids:
        frozen_attempt_ids = set(
            (
                await session.execute(
                    select(ExecutionAttempt.id)
                    .join(EvidenceSet, EvidenceSet.id == ExecutionAttempt.evidence_set_id)
                    .where(
                        ExecutionAttempt.id.in_(attempt_ids),
                        ExecutionAttempt.status.in_(("ready", "completed")),
                        EvidenceSet.status == "frozen",
                    )
                )
            ).scalars()
        )
    frozen = [
        candidate
        for candidate in reused
        if candidate.metadata.get("source_attempt_id") in frozen_attempt_ids
    ]
    rendered = _render_evidence(frozen)
    if not rendered:
        return ""
    return render_prompt(
        prompts,
        "chat.expert.research_evidence",
        evidence=rendered,
    )


def combine_expert_chat_context(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part.strip())
