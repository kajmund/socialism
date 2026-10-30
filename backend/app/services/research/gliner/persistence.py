"""Persistence for GLiNER2 span-proposal outcomes.

A need's findings are only usable once EVERY qualified unit has been scanned
and all batches' verdicts are aggregated: partial batches persist as
non-usable checkpoints, and the final batch derives findings across the
scanned set (earlier batches included). The wave assessment row is
invalidated in the SAME transaction as the items, so a cancellation can
never leave new evidence behind a stale assessment.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from app.services.research.gliner.contract import (
    AMBIGUOUS,
    DERIVATION,
    NEED_LABELS,
    REJECTED,
    VERIFIED,
    ContractFinding,
    SpanVerdict,
    canon,
    derive_findings,
)
from app.services.research.gliner.proposal import (
    PER_NEED_JEV_BUDGET,
    SPAN_CAP,
    STEP_JEV_BUDGET,
)

_REASON_TEXT = {
    SPAN_CAP: "spann-taket per enhet nåddes",
    PER_NEED_JEV_BUDGET: "JEV-budgeten för behovet tog slut",
    STEP_JEV_BUDGET: "steg-budgeten för JEV tog slut",
}

#: Provenance key holding a batch's raw verdict slots (reused by later batches).
SCANNED_SPANS = "scanned_spans"


@dataclass(frozen=True)
class PersistContext:
    fingerprints: dict[str, str]
    config_fingerprints: dict[str, str]
    processed_units: dict[str, list[str]]
    complete_by_need: dict[str, bool]
    attempt_id: str
    assessment_pass: int


@dataclass(frozen=True)
class NeedPersistenceInput:
    need: object
    verdicts: list[SpanVerdict]  # this batch's raw verdicts
    findings: list[ContractFinding]  # aggregated over all batches (complete only)
    complete: bool
    truncation_reasons: frozenset[str]
    unprocessed: list[dict[str, object]] = field(default_factory=list)
    # Candidates an earlier truncation left unprocessed and this run could not
    # resolve either: they keep the need incomplete.
    unresolved: list[dict[str, object]] = field(default_factory=list)
    fingerprint: str = ""
    config_fingerprint: str = ""
    processed_units: list[str] = field(default_factory=list)


def _scan_provenance(verdicts: list[SpanVerdict]) -> list[dict[str, object]]:
    return [
        {
            "span": verdict.span,
            "need_type": verdict.need_type,
            "choice": verdict.choice,
            "role": verdict.role,
            "prompt_version": verdict.prompt_version,
            "unit_id": verdict.unit_id,
        }
        for verdict in verdicts
    ]


def build_item_lines(
    findings: list[ContractFinding],
) -> tuple[list[str], list[dict], list[dict]]:
    """Build excerpt lines, claim rows and provenance rows for one need."""
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


def _incomplete_excerpt(
    complete: bool,
    reasons: frozenset[str],
    unresolved: list[dict[str, object]],
) -> str:
    """Name every reason the evidence is unusable — partial AND truncated."""
    parts: list[str] = []
    if not complete:
        parts.append("ytterligare enheter återstår att skanna")
    if reasons:
        texts = ", ".join(
            _REASON_TEXT.get(reason, reason) for reason in sorted(reasons)
        )
        parts.append(f"{texts} innan alla kandidater verifierades")
    if unresolved:
        parts.append(
            f"{len(unresolved)} kandidat(er) från en tidigare trunkering "
            "kunde inte verifieras"
        )
    if not parts:
        parts.append("ofullständig verifiering")
    return "Ofullständig verifiering: " + "; ".join(parts) + "."


def _build_metadata(
    data: NeedPersistenceInput,
    *,
    claims: list[dict],
    provenance: list[dict],
) -> dict[str, object]:
    reasons = sorted(data.truncation_reasons)
    incomplete = (not data.complete) or bool(reasons) or bool(data.unresolved)
    unprocessed = list(data.unprocessed) + list(data.unresolved)
    metadata: dict[str, object] = {
        "derived": True,
        "primary_source": False,
        "source_nature": "secondary",
        "derivation": DERIVATION,
        "input_fingerprint": data.fingerprint,
        "proposal_config_fingerprint": data.config_fingerprint,
        "processed_units": data.processed_units,
        SCANNED_SPANS: _scan_provenance(data.verdicts),
        "need_types": data.need.span_types,
        "need_role": getattr(data.need, "span_role", "") or "",
        "incomplete": incomplete,
        "incomplete_reason": (
            "truncated"
            if reasons or data.unresolved
            else ("partial_batch" if not data.complete else "")
        ),
        "truncation_reasons": reasons,
        "unprocessed_candidates": unprocessed,
        "verified_spans": [
            finding for finding in provenance if finding["state"] == VERIFIED
        ],
        "conflicting_spans": [
            finding for finding in provenance if finding["state"] == AMBIGUOUS
        ],
        "rejected_spans": [
            finding for finding in provenance if finding["state"] == REJECTED
        ],
        "derived_claims": claims,
        "empty_proposals": not (data.verdicts or unprocessed or data.findings),
    }
    return metadata


async def _persist_need_item(
    write_session: object,
    *,
    data: NeedPersistenceInput,
    evidence_set_id: str,
) -> list[object]:
    """Persist one need's checkpoint/findings and return stored items."""
    from app.services.execution.service import add_evidence_items
    from app.services.research.models import research_evidence

    lines, claims, provenance = build_item_lines(data.findings)
    reasons = sorted(data.truncation_reasons)
    incomplete = (not data.complete) or bool(reasons) or bool(data.unresolved)
    has_usable_content = (not incomplete) and bool(claims)
    if incomplete:
        lines = [
            _incomplete_excerpt(
                data.complete, data.truncation_reasons, data.unresolved
            )
        ]
        claims, provenance = [], []
    elif not lines:
        lines = (
            ["Inga verifierade fynd: alla förslag avvisades."]
            if data.findings
            else ["Inga kandidater föreslogs."]
        )
    metadata = _build_metadata(data, claims=claims, provenance=provenance)
    digest = hashlib.sha256(
        json.dumps(
            {
                "provenance": provenance,
                "fingerprint": data.fingerprint,
                "config_fingerprint": data.config_fingerprint,
                "processed_units": data.processed_units,
                "incomplete": incomplete,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()[:16]
    for claim in claims:
        claim["research_need_id"] = data.need.id
        claim["id"] = hashlib.sha256(
            f"{data.need.id}:{digest}:{claim['id']}".encode()
        ).hexdigest()
    stored = await add_evidence_items(
        write_session,
        evidence_set_id=evidence_set_id,
        items=[
            research_evidence(
                research_need_id=data.need.id,
                source_type="derived",
                status="found" if has_usable_content else "not_found",
                title=data.need.question,
                excerpt="\n".join(lines),
                provider="gliner_span_proposer",
                source_id=f"gliner:{data.need.id}:{digest}",
                metadata=metadata,
            )
        ],
    )
    return stored


def _prior_verdicts(
    items: list[object], need: object, config_fingerprint: str
) -> list[SpanVerdict]:
    """Rebuild earlier batches' verdicts from checkpoints of the SAME config."""
    prior: list[SpanVerdict] = []
    for item in items:
        provenance = item.provenance or {}
        if provenance.get("derivation") != DERIVATION:
            continue
        if item.research_need_id != need.id:
            continue
        if provenance.get("proposal_config_fingerprint") != config_fingerprint:
            continue
        for entry in provenance.get(SCANNED_SPANS) or []:
            prior.append(
                SpanVerdict(
                    span=str(entry.get("span") or ""),
                    need_type=str(entry.get("need_type") or ""),
                    prompt_version=str(entry.get("prompt_version") or ""),
                    choice=str(entry.get("choice") or "UNCERTAIN"),
                    unit_id=str(entry.get("unit_id") or ""),
                    unit_text="",
                    role=entry.get("role"),
                    role_locked=True,
                )
            )
    return prior


def aggregate_findings(need: object, verdicts: list[SpanVerdict]) -> list[ContractFinding]:
    """Derive findings over ALL scanned batches for one need."""
    need_role = getattr(need, "span_role", "") or ""
    findings: list[ContractFinding] = []
    for need_type in dict.fromkeys(verdict.need_type for verdict in verdicts):
        scoped = [verdict for verdict in verdicts if verdict.need_type == need_type]
        findings.extend(
            derive_findings(scoped, need_type=need_type, need_role=need_role)
        )
    return findings


async def persist_findings_and_invalidate(
    config: object,
    targets: list[object],
    outcome: object,
    *,
    context: PersistContext,
) -> set[str]:
    """Persist findings/checkpoints and invalidate the wave assessment.

    The assessment row is deleted in the same transaction as the items: a
    cancellation between persist and refresh can never leave the new evidence
    behind a stale assessment.
    """
    from app.services.execution.service import (
        get_research_assessment,
        list_evidence_items,
    )

    persisted: set[str] = set()
    async with config.factory() as write_session:
        items = await list_evidence_items(write_session, config.evidence_set_id)
        for need in targets:
            if need.id not in outcome.proposed_needs:
                continue
            complete = context.complete_by_need.get(need.id, False)
            reasons = outcome.truncation_reasons.get(need.id, frozenset())
            unresolved = outcome.unresolved.get(need.id, [])
            current = outcome.verdicts_by_need.get(need.id, [])
            config_fingerprint = context.config_fingerprints.get(need.id, "")
            findings = (
                aggregate_findings(
                    need,
                    _prior_verdicts(items, need, config_fingerprint) + current,
                )
                if complete and not reasons and not unresolved
                else []
            )
            stored = await _persist_need_item(
                write_session,
                data=NeedPersistenceInput(
                    need=need,
                    verdicts=current,
                    findings=findings,
                    complete=complete,
                    truncation_reasons=reasons,
                    unprocessed=outcome.unprocessed.get(need.id, []),
                    unresolved=outcome.unresolved.get(need.id, []),
                    fingerprint=context.fingerprints[need.id],
                    config_fingerprint=context.config_fingerprints.get(need.id, ""),
                    processed_units=context.processed_units.get(need.id, []),
                ),
                evidence_set_id=config.evidence_set_id,
            )
            persisted.update(item.id for item in stored)
        if persisted:
            superseded = await get_research_assessment(
                write_session,
                context.attempt_id,
                assessment_pass=context.assessment_pass,
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
