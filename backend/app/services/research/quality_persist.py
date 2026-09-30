"""Persist evidence quality drafts. Eager need scoring lives here so execution.py does not grow."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import EvidenceSetItem, ResearchEvidenceQuality
from app.observability.research import record_barrier_quality_items, record_eager_quality_items
from app.services.execution.service import (
    list_evidence_items,
    list_evidence_quality,
    persist_evidence_quality,
)
from app.services.research.assessment import ResearchAssessor
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.provider import KnowledgeProviderDescriptor
from app.services.research.quality import (
    EVIDENCE_QUALITY_POLICY_VERSION,
    EvidenceQualityDraft,
    EvidenceRelevanceAssessor,
    QualityEvidenceInput,
    QualityFlag,
    assess_evidence_quality,
    quality_model_identity_key,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EagerQualityBind:
    reuse_assessor: ResearchAssessor
    descriptors: tuple[KnowledgeProviderDescriptor, ...]
    relevance_assessor: EvidenceRelevanceAssessor | None


def quality_input_from_item(item: EvidenceSetItem) -> QualityEvidenceInput:
    return QualityEvidenceInput(
        item_id=item.id,
        original_evidence_id=item.original_evidence_id,
        research_need_id=item.research_need_id,
        source_type=item.source_type,
        status=item.status,
        title=item.title,
        excerpt=item.excerpt,
        locator=item.locator,
        source_id=item.source_id,
        source_url=item.source_url,
        provider=item.provider,
        provenance=dict(item.provenance or {}),
        retrieved_at=item.retrieved_at,
        content_hash=item.content_hash,
    )


def quality_draft_from_row(row: ResearchEvidenceQuality) -> EvidenceQualityDraft:
    raw_flags = row.flags if isinstance(row.flags, list) else []
    flags = []
    for item in raw_flags:
        if isinstance(item, dict) and item.get("code"):
            flags.append(QualityFlag(code=str(item["code"]), detail=str(item.get("detail") or "")))
    return EvidenceQualityDraft(
        evidence_set_item_id=row.evidence_set_item_id,
        original_evidence_id=row.original_evidence_id,
        scoring_policy_version=row.scoring_policy_version,
        authority=row.authority,
        relevance=row.relevance,
        currentness=row.currentness,
        source_nature=row.source_nature,
        source_timestamp=row.source_timestamp,
        independence_key=row.independence_key,
        independent_source_count=row.independent_source_count,
        flags=flags,
        rationale=row.rationale,
        declared_signals=dict(row.declared_signals or {}),
        model_provider=row.model_provider,
        model_name=row.model_name,
        model_version=row.model_version,
    )


def _draft_key(draft: EvidenceQualityDraft) -> tuple[str, str, str]:
    return (
        draft.evidence_set_item_id,
        draft.scoring_policy_version,
        quality_model_identity_key(
            model_provider=draft.model_provider,
            model_name=draft.model_name,
            model_version=draft.model_version,
        ),
    )


def _existing_keys(rows: Sequence[ResearchEvidenceQuality]) -> set[tuple[str, str, str]]:
    return {
        (row.evidence_set_item_id, row.scoring_policy_version, row.model_identity_key)
        for row in rows
    }


def quality_by_item(
    drafts: list[EvidenceQualityDraft],
) -> dict[str, EvidenceQualityDraft]:
    return {draft.evidence_set_item_id: draft for draft in drafts}


async def persist_evidence_quality_drafts(
    session: AsyncSession,
    *,
    evidence_set_id: str,
    plan: ResearchPlan,
    descriptors: tuple[KnowledgeProviderDescriptor, ...],
    relevance_assessor: EvidenceRelevanceAssessor | None,
    item_ids: set[str] | None = None,
    record_barrier: bool = True,
) -> list[EvidenceQualityDraft]:
    """Score persisted items. Existing (item, policy, model) rows are left intact."""
    items = await list_evidence_items(session, evidence_set_id)
    existing = await list_evidence_quality(
        session,
        evidence_set_id,
        scoring_policy_version=EVIDENCE_QUALITY_POLICY_VERSION,
    )
    existing_keys = _existing_keys(existing)
    inputs = [
        quality_input_from_item(item)
        for item in items
        if item_ids is None or item.id in item_ids
    ]
    # Derived evidence is a durable checkpoint before external scoring.
    await session.commit()
    drafts = await assess_evidence_quality(
        inputs,
        needs=plan.needs,
        descriptors=descriptors,
        relevance_assessor=relevance_assessor,
    )
    missing = [draft for draft in drafts if _draft_key(draft) not in existing_keys]
    if missing:
        await persist_evidence_quality(session, evidence_set_id=evidence_set_id, drafts=missing)
    if record_barrier:
        record_barrier_quality_items(len(missing))
    stored = await list_evidence_quality(
        session,
        evidence_set_id,
        scoring_policy_version=EVIDENCE_QUALITY_POLICY_VERSION,
    )
    return [quality_draft_from_row(row) for row in stored]


async def score_need_quality_eager(
    *,
    factory: async_sessionmaker[AsyncSession],
    persist_lock: asyncio.Lock,
    evidence_set_id: str,
    need: ResearchNeed,
    stored: Sequence[EvidenceSetItem],
    bind: EagerQualityBind | None,
    raise_if_fenced: Callable[[], None],
) -> None:
    """Score this need's owned stored items after persist. Failures do not fail the need."""
    owned_ids = {item.id for item in stored if item.research_need_id == need.id}
    if bind is None or not owned_ids:
        return
    try:
        raise_if_fenced()
        async with persist_lock, factory() as read_session:
            raise_if_fenced()
            items = await list_evidence_items(read_session, evidence_set_id)
        batch = [item for item in items if item.research_need_id == need.id]
        drafts = await assess_evidence_quality(
            [quality_input_from_item(item) for item in batch],
            needs=[need],
            descriptors=bind.descriptors,
            relevance_assessor=bind.relevance_assessor,
        )
        raise_if_fenced()
        async with persist_lock, factory() as persist_session:
            raise_if_fenced()
            existing = await list_evidence_quality(
                persist_session,
                evidence_set_id,
                scoring_policy_version=EVIDENCE_QUALITY_POLICY_VERSION,
            )
            missing = [
                draft
                for draft in drafts
                if draft.evidence_set_item_id in owned_ids
                and _draft_key(draft) not in _existing_keys(existing)
            ]
            if missing:
                await persist_evidence_quality(
                    persist_session, evidence_set_id=evidence_set_id, drafts=missing
                )
            await persist_session.commit()
            record_eager_quality_items(len(missing))
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "research_eager_quality_failed research_need_id=%s",
            need.id,
            exc_info=True,
        )
