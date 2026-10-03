"""Read-only reusable research evidence for expert chat."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import EvidenceSet, EvidenceSetItem, ExecutionAttempt, ExecutionRun
from app.services.knowledge.models import KnowledgeScope
from app.services.legal_research_result import legal_result_summary
from app.services.prompt_catalog import render_prompt
from app.services.research.models import (
    RESEARCH_SOURCE_TYPES,
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
)
from app.services.research.graph_lookup import lookup_question


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
        if item.legal_result is not None:
            lines.extend(legal_result_summary(item.legal_result))
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
    assume_caller_idle: bool = True,
) -> str:
    """Return Graph v2 evidence that appeared in a frozen customer attempt.

    This path never creates a Run, Attempt, question, or provider request.
    Case-scoped evidence is excluded because library chat has no document case.
    """
    from app.services.research.execution import _session_factory

    if assume_caller_idle and session.in_transaction():
        raise RuntimeError("Release chat input transaction before reading reusable Graph evidence")
    reused = await lookup_question(
        _session_factory(session),
        ResearchNeed(
            id="expert_chat_reuse",
            question=question,
            why_needed="",
            source_types=list(RESEARCH_SOURCE_TYPES),
        ),
        ResearchContext(scope=KnowledgeScope(customer_id=customer_id)),
    )
    async with _session_factory(session)() as read_session:
        frozen_refs = await _frozen_graph_refs(read_session, customer_id, reused)
    frozen = [
        candidate
        for candidate in reused
        if (candidate.metadata["graph_fact_ids"][0], candidate.metadata["document_version_id"])
        in frozen_refs
        and candidate.metadata["reuse"]["freshness"] == "fresh"
    ]
    rendered = _render_evidence(frozen)
    if not rendered:
        return ""
    return render_prompt(
        prompts,
        "chat.expert.research_evidence",
        evidence=rendered,
    )


async def _frozen_graph_refs(session, customer_id, candidates) -> set[tuple[str, str]]:
    document_ids = [item.source_id for item in candidates]
    if not document_ids:
        return set()
    rows = (await session.scalars(select(EvidenceSetItem)
        .join(EvidenceSet, EvidenceSet.id == EvidenceSetItem.evidence_set_id)
        .join(ExecutionAttempt, ExecutionAttempt.evidence_set_id == EvidenceSet.id)
        .join(ExecutionRun, ExecutionRun.id == ExecutionAttempt.run_id)
        .where(ExecutionRun.customer_id == customer_id, EvidenceSet.status == "frozen",
               ExecutionAttempt.status.in_(("ready", "completed")),
               EvidenceSetItem.provider == "graph_v2", EvidenceSetItem.status == "found",
               EvidenceSetItem.source_id.in_(document_ids)))).all()
    return {(fact_id, row.provenance.get("document_version_id"))
            for row in rows for fact_id in row.provenance.get("graph_fact_ids", [])}


def combine_expert_chat_context(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part.strip())


_NO_FROZEN_EVIDENCE = "Ingen tidigare fryst researchevidens matchar frågan."


def evidence_tool_handler_for_chat(
    session: AsyncSession,
    *,
    customer_id: int,
    prompts: dict[str, str],
) -> Callable[[dict[str, Any]], Awaitable[str]]:
    async def handle(arguments: dict[str, Any]) -> str:
        question = str(arguments.get("question") or "").strip()
        if not question:
            raise ValueError("lookup_research_evidence kräver en fråga.")
        # The chat turn may still hold a read transaction. The lookup opens its own sessions.
        rendered = await reusable_expert_chat_evidence_context(
            session,
            customer_id=customer_id,
            question=question,
            prompts=prompts,
            assume_caller_idle=False,
        )
        return rendered or _NO_FROZEN_EVIDENCE

    return handle
