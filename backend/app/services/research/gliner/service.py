"""Opt-in GLiNER2 span-proposal step for incomplete research needs.

The tool is SWE's choice, never a mandatory step: it runs only when the
global switch is on, the research run opted in, the assessment is
insufficient, and a need declares span types and still lacks a proposal.
Findings enter the EvidenceSet as derived items with full provenance — they
never set RESOLVED by themselves; the normal assessment decides their use.

After persisting findings the step scores their quality and runs the wave
assessor again for the next assessment pass, so the new evidence is judged
before the wave decision and the freeze — never frozen unassessed.

Database discipline (root rule): all inputs are materialized and committed
before any GLiNER2/Jev call; results persist in new short transactions.
No connection is held across external calls.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

from app.config import settings
from app.jev.system import HttpJevSystemOne
from app.observability.research import record_gliner_inference, record_jev_call
from app.services.research.gliner.contract import (
    AMBIGUOUS,
    NEED_LABELS,
    REJECTED,
    VERIFIED,
    ContractFinding,
    SpanVerdict,
    canon,
    derive_findings,
    verification_question,
)
from app.services.research.gliner.proposer import ProposalUnit, propose_spans

#: Run-level opt-in key in ExecutionAttempt.configuration_snapshot.
OPT_IN_KEY = "gliner_span_proposer"

#: Item provenance marker; needs with such an item are never proposed twice.
DERIVATION = "gliner_span_proposal"

#: Reverse label map so each proposal is verified against its own type.
LABEL_TO_TYPE = {label: span_type for span_type, label in NEED_LABELS.items()}

#: Schema-valid Jev choices. Anything else is a loud schema error.
JEV_CHOICES = frozenset({"YES", "NO", "UNCERTAIN"})


class GlinerStepError(Exception):
    """The enabled step failed. Research fails closed — never silently skips."""


@dataclass(frozen=True)
class GlinerStepReport:
    needs_considered: int
    units_scanned: int
    inferences: int
    jev_calls: int
    findings_persisted: int
    jev_budget_truncated: bool = False


@dataclass(frozen=True)
class GlinerStepResult:
    """Refreshed assessment plus the step's economy report."""

    assessment: object
    report: GlinerStepReport


@dataclass(frozen=True)
class ProposalPhaseStats:
    units: int
    jev_calls: int
    jev_budget_truncated: bool


def is_opted_in(attempt: object) -> bool:
    snapshot = getattr(attempt, "configuration_snapshot", None) or {}
    return snapshot.get(OPT_IN_KEY) is True


def enabled_and_opted_in(attempt: object) -> bool:
    return settings.gliner_span_proposer.enabled and is_opted_in(attempt)


def _labels_for(need: object) -> tuple[str, ...]:
    span_types = getattr(need, "span_types", ()) or ()
    return tuple(NEED_LABELS[span_type] for span_type in span_types)[:3]


def _target_needs(plan: object, draft: object) -> list[object]:
    """Needs that are insufficient AND declare span types."""
    insufficient = {
        row.research_need_id for row in draft.need_assessments if not row.sufficient
    }
    return [
        need
        for need in plan.needs
        if need.id in insufficient and getattr(need, "span_types", None)
    ]


def _has_prior_proposal(need_id: str, items: list[object]) -> bool:
    """Retry guard: a need that already has a proposal item never runs again."""
    return any(
        item.research_need_id == need_id
        and (item.provenance or {}).get("derivation") == DERIVATION
        for item in items
    )


def _unit_texts(need: object, items: list[object]) -> tuple[ProposalUnit, ...]:
    units: list[ProposalUnit] = []
    seen: set[str] = set()
    for item in items:
        if item.research_need_id != need.id:
            continue
        if item.status != "found" or not item.excerpt:
            continue
        if (item.provenance or {}).get("derivation") == DERIVATION:
            continue
        if item.id in seen:
            continue
        seen.add(item.id)
        units.append(
            ProposalUnit(
                unit_id=item.id,
                text=item.excerpt[: settings.gliner_span_proposer.max_excerpt_chars],
            )
        )
        if len(units) >= settings.gliner_span_proposer.max_units_per_need:
            break
    return tuple(units)


async def _verify_span(
    jev: object,
    *,
    unit: ProposalUnit,
    need_type: str,
    span: str,
) -> SpanVerdict:
    question = verification_question(need_type, span)
    started = time.perf_counter()
    result = await jev.ask(
        state={"text": unit.text},
        questions=question["question"],
        model=settings.research_jev_model or settings.jev_model,
        timeout_seconds=settings.jev_timeout_seconds,
    )
    record_jev_call((time.perf_counter() - started) * 1000)
    answer = result.answers.get("evidence", {})
    raw_choice = answer.get("choice")
    choice = str(raw_choice).upper() if raw_choice else ""
    if choice not in JEV_CHOICES:
        raise GlinerStepError(
            f"Jev returned an invalid choice {raw_choice!r} for span {span!r} "
            f"in unit {unit.unit_id!r}"
        )
    return SpanVerdict(
        span=span,
        need_type=need_type,
        prompt_version=str(question["prompt_version"]),
        choice=choice,
        unit_id=unit.unit_id,
        unit_text=unit.text,
    )


async def _proposal_phase(
    jev: object,
    targets: list[object],
    units_by_need: dict[str, tuple[ProposalUnit, ...]],
) -> tuple[dict[str, list[ContractFinding]], ProposalPhaseStats]:
    """GLiNER2 + Jev for every targeted need. No database access here."""
    findings_by_need: dict[str, list[ContractFinding]] = {}
    units_total = 0
    jev_total = 0
    truncated = False
    per_need_budget = settings.gliner_span_proposer.max_jev_calls_per_need
    step_budget = settings.gliner_span_proposer.max_jev_calls_per_step
    for need in targets:
        if truncated:
            break
        units = units_by_need[need.id]
        units_total += len(units)
        need_role = getattr(need, "span_role", "") or ""
        proposed = await propose_spans(units, _labels_for(need))
        by_unit = {entry.unit_id: entry for entry in proposed}
        need_verdicts: list[SpanVerdict] = []
        need_calls = 0
        for unit in units:
            entry = by_unit.get(unit.unit_id)
            if entry is None or not entry.proposals:
                continue
            for proposal in entry.proposals[: settings.gliner_span_proposer.max_spans_per_unit]:
                need_type = LABEL_TO_TYPE.get(proposal.label)
                if need_type is None:
                    continue
                if need_calls >= per_need_budget or jev_total >= step_budget:
                    truncated = True
                    break
                need_verdicts.append(
                    await _verify_span(
                        jev, unit=unit, need_type=need_type, span=proposal.span
                    )
                )
                need_calls += 1
                jev_total += 1
            if truncated:
                break
        # Aggregate across every scanned unit: competing values in different
        # units must still collide into one AMBIGUOUS finding.
        for need_type in dict.fromkeys(v.need_type for v in need_verdicts):
            scoped = [v for v in need_verdicts if v.need_type == need_type]
            findings_by_need.setdefault(need.id, []).extend(
                derive_findings(scoped, need_type=need_type, need_role=need_role)
            )
    return findings_by_need, ProposalPhaseStats(
        units=units_total, jev_calls=jev_total, jev_budget_truncated=truncated
    )


def _need_item_lines(findings: list[ContractFinding]) -> tuple[list[str], list[dict], list[dict]]:
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


async def _persist_findings(
    config: object,
    targets: list[object],
    findings_by_need: dict[str, list[ContractFinding]],
    stats: ProposalPhaseStats,
) -> set[str]:
    """Persist verified and conflicting findings as derived evidence items."""
    from app.services.execution.service import add_evidence_items
    from app.services.research.models import research_evidence

    persisted: set[str] = set()
    async with config.factory() as write_session:
        for need in targets:
            findings = findings_by_need.get(need.id, [])
            if not findings:
                continue
            lines, claims, provenance = _need_item_lines(findings)
            # Rejected-only runs still persist a not_found checkpoint: it keeps
            # the rejected provenance visible and makes the retry idempotent.
            has_content = bool(lines)
            if not has_content:
                lines = ["Inga verifierade fynd: alla förslag avvisades."]
            digest = hashlib.sha256(
                json.dumps(provenance, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:16]
            for claim in claims:
                claim["research_need_id"] = need.id
                claim["id"] = hashlib.sha256(
                    f"{need.id}:{digest}:{claim['id']}".encode()
                ).hexdigest()
            stored = await add_evidence_items(
                write_session,
                evidence_set_id=config.evidence_set_id,
                items=[
                    research_evidence(
                        research_need_id=need.id,
                        source_type="derived",
                        status="found" if has_content else "not_found",
                        title=need.question,
                        excerpt="\n".join(lines),
                        provider="gliner_span_proposer",
                        source_id=f"gliner:{need.id}:{digest}",
                        metadata={
                            "derived": True,
                            "primary_source": False,
                            "source_nature": "secondary",
                            "derivation": DERIVATION,
                            "need_types": need.span_types,
                            "need_role": getattr(need, "span_role", "") or "",
                            "jev_budget_truncated": stats.jev_budget_truncated,
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
                        },
                    )
                ],
            )
            persisted.update(item.id for item in stored)
        await write_session.commit()
    return persisted


async def _refresh_assessment(
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


async def maybe_run_gliner_step(
    config: object,
    session: object,
    *,
    attempt: object,
    plan: object,
    assessment: object,
    wave: int,
) -> GlinerStepResult | None:
    """Run the span-proposal step for incomplete needs; no-op when off.

    Returns the refreshed assessment (next pass) and the economy report after
    findings are persisted and scored, or None when the step did not run. The caller's session is
    used only for the input phase and committed before any external call.
    Failures propagate — an enabled step never degrades silently.
    """
    if not enabled_and_opted_in(attempt):
        return None
    draft = _assessment_draft(assessment)
    if draft.result != "insufficient":
        return None
    targets = _target_needs(plan, draft)
    if not targets:
        return None

    # Input phase: materialize units per need and release the connection.
    from app.services.execution.service import list_evidence_items

    items = await list_evidence_items(session, config.evidence_set_id)
    targets = [need for need in targets if not _has_prior_proposal(need.id, items)]
    units_by_need = {need.id: _unit_texts(need, items) for need in targets}
    targets = [need for need in targets if units_by_need[need.id]]
    if not targets:
        return None
    await session.commit()

    findings_by_need, stats = await _proposal_phase(
        HttpJevSystemOne(), targets, units_by_need
    )
    record_gliner_inference(stats.units)
    persisted_ids = await _persist_findings(config, targets, findings_by_need, stats)
    if not persisted_ids:
        return None
    refreshed = await _refresh_assessment(
        config, attempt, plan=plan, wave=wave, persisted_ids=persisted_ids
    )
    return GlinerStepResult(
        assessment=refreshed,
        report=GlinerStepReport(
            needs_considered=len(targets),
            units_scanned=stats.units,
            inferences=stats.units,
            jev_calls=stats.jev_calls,
            findings_persisted=len(persisted_ids),
            jev_budget_truncated=stats.jev_budget_truncated,
        ),
    )


def _assessment_draft(assessment: object) -> object:
    """Persisted assessments store JSON rows; convert before reading fields."""
    from app.services.research.assessment import assessment_draft_from_row

    return assessment_draft_from_row(assessment)
