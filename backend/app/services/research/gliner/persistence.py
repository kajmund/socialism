"""Persistence for GLiNER2 span-proposal outcomes.

Findings and checkpoints enter the EvidenceSet as derived items with full
provenance; the wave assessment row is invalidated in the SAME transaction so
a cancellation can never leave new evidence behind a stale assessment. The
new items are then scored and the wave pass is recomputed before the decision.
"""

from __future__ import annotations

import hashlib
import json

from app.services.research.gliner.contract import (
    AMBIGUOUS,
    DERIVATION,
    NEED_LABELS,
    REJECTED,
    VERIFIED,
    ContractFinding,
    canon,
)


def build_item_lines(
    findings: list[ContractFinding],
) -> tuple[list[str], list[dict], list[dict]]:
    """Build excerpt lines, claim rows and provenance rows for one need.

    Conflicts stay visible: AMBIGUOUS spans are written into the excerpt and
    metadata, and REJECTED spans are recorded in provenance.
    """
    lines: list[str] = []
    claims: list[dict] = []
    provenance: list[dict] = []
    for finding in findings:
        predicate = NEED_LABELS.get(finding.need_type, finding.need_type)
        provenance.append(
            {
                "span": finding.span,
                "value": finding.value,
                "need_type": finding.need_type,
                "state": finding.state,
                "role": finding.role,
                "prompt_version": finding.prompt_version,
                "unit_id": finding.unit_id,
                "choice": finding.choice,
            }
        )
        if finding.state == VERIFIED:
            lines.append(f"{predicate}: {finding.span}")
            claims.append(
                {
                    "id": hashlib.sha256(
                        f"{finding.need_type}:{canon(finding.span)}".encode()
                    ).hexdigest(),
                    "predicate": predicate,
                    "value": finding.span,
                    "derived": True,
                }
            )
        elif finding.state == AMBIGUOUS:
            lines.append(f"Motstridigt värde ({predicate}): {finding.span}")
    return lines, claims, provenance


async def _persist_need_item(
    write_session: object,
    *,
    need: object,
    findings: list[ContractFinding],
    truncated: bool,
    unprocessed: list[dict[str, object]],
    fingerprint: str,
    evidence_set_id: str,
) -> list[object]:
    """Persist one need's checkpoint/findings and return stored items."""
    from app.services.execution.service import add_evidence_items
    from app.services.research.models import research_evidence

    lines, claims, provenance = build_item_lines(findings)
    has_usable_content = bool(lines) and not truncated
    metadata_extra: dict[str, object] = {}
    if truncated:
        # A truncated need has NOT seen every candidate: never usable as
        # verified evidence. Keep the partial and unprocessed spans visible.
        metadata_extra = {
            "incomplete": True,
            "partial_spans": provenance,
            "unprocessed_candidates": unprocessed,
        }
        lines = [
            "Ofullständig verifiering: JEV-budgeten tog slut innan alla "
            "kandidater verifierades."
        ]
        claims = []
        provenance = []
    elif not lines:
        if findings:
            lines = ["Inga verifierade fynd: alla förslag avvisades."]
        else:
            lines = ["Inga kandidater föreslogs."]
    digest = hashlib.sha256(
        json.dumps(
            {
                "provenance": provenance,
                "fingerprint": fingerprint,
                "incomplete": truncated,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()[:16]
    for claim in claims:
        claim["research_need_id"] = need.id
        claim["id"] = hashlib.sha256(
            f"{need.id}:{digest}:{claim['id']}".encode()
        ).hexdigest()
    stored = await add_evidence_items(
        write_session,
        evidence_set_id=evidence_set_id,
        items=[
            research_evidence(
                research_need_id=need.id,
                source_type="derived",
                status="found" if has_usable_content else "not_found",
                title=need.question,
                excerpt="\n".join(lines),
                provider="gliner_span_proposer",
                source_id=f"gliner:{need.id}:{digest}",
                metadata={
                    "derived": True,
                    "primary_source": False,
                    "source_nature": "secondary",
                    "derivation": DERIVATION,
                    "input_fingerprint": fingerprint,
                    "need_types": need.span_types,
                    "need_role": getattr(need, "span_role", "") or "",
                    "jev_budget_truncated": truncated,
                    "verified_spans": [
                        finding
                        for finding in provenance
                        if finding["state"] == VERIFIED
                    ],
                    "conflicting_spans": [
                        finding
                        for finding in provenance
                        if finding["state"] == AMBIGUOUS
                    ],
                    "rejected_spans": [
                        finding
                        for finding in provenance
                        if finding["state"] == REJECTED
                    ],
                    "derived_claims": claims,
                    "empty_proposals": not findings and not truncated,
                    **metadata_extra,
                },
            )
        ],
    )
    return stored


async def persist_findings_and_invalidate(
    config: object,
    targets: list[object],
    outcome: object,
    *,
    fingerprints: dict[str, str],
    attempt_id: str,
    assessment_pass: int,
) -> set[str]:
    """Persist findings/checkpoints and invalidate the wave assessment.

    The assessment row is deleted in the same transaction as the items: a
    cancellation between persist and refresh can never leave the new evidence
    behind a stale assessment.
    """
    from app.services.execution.service import get_research_assessment

    persisted: set[str] = set()
    async with config.factory() as write_session:
        for need in targets:
            if need.id not in outcome.proposed_needs:
                continue
            stored = await _persist_need_item(
                write_session,
                need=need,
                findings=outcome.findings_by_need.get(need.id, []),
                truncated=need.id in outcome.truncated_needs,
                unprocessed=outcome.unprocessed.get(need.id, []),
                fingerprint=fingerprints[need.id],
                evidence_set_id=config.evidence_set_id,
            )
            persisted.update(item.id for item in stored)
        if persisted:
            superseded = await get_research_assessment(
                write_session, attempt_id, assessment_pass=assessment_pass
            )
            if superseded is not None:
                await write_session.delete(superseded)
                await write_session.flush()
        await write_session.commit()
    return persisted


async def refresh_assessment(
    config: object,
    attempt: object,
    *,
    plan: object,
    wave: int,
    persisted_ids: set[str],
) -> object:
    """Score the new items and replace this wave's assessment.

    The wave pass is recomputed with the new evidence so the decision and the
    freeze judge it. The pass number is the current wave's — never a future
    pass: the next wave must still recompute its own assessment after its
    follow-up retrieval.
    """
    from app.services.execution.service import get_research_assessment
    from app.services.research.execution import (
        _assess_persisted_evidence,
        quality_descriptors,
    )
    from app.services.research.followup import next_assessment_pass
    from app.services.research.quality_persist import persist_evidence_quality_drafts

    descriptors = quality_descriptors(config.router, config.provider_descriptors)
    relevance_assessor = config.relevance_assessor
    assessment_pass = next_assessment_pass(wave)

    async with config.factory() as assess_session:
        quality = await persist_evidence_quality_drafts(
            assess_session,
            evidence_set_id=config.evidence_set_id,
            plan=plan,
            descriptors=descriptors,
            relevance_assessor=relevance_assessor,
            item_ids=persisted_ids,
        )
        superseded = await get_research_assessment(
            assess_session, attempt.id, assessment_pass=assessment_pass
        )
        if superseded is not None:
            await assess_session.delete(superseded)
            await assess_session.flush()
        refreshed = await _assess_persisted_evidence(
            assess_session,
            attempt=attempt,
            evidence_set_id=config.evidence_set_id,
            plan=plan,
            assessor=config.assessor,
            assessment_pass=assessment_pass,
            quality=quality,
            descriptors=descriptors,
            relevance_assessor=relevance_assessor,
        )
        await assess_session.commit()
    return refreshed
