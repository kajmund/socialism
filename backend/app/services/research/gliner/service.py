"""Opt-in GLiNER2 span-proposal step for incomplete research needs.

The tool is SWE's choice, never a mandatory step: it runs only when the
global switch is on, the research run opted in, the assessment is
insufficient, and a need declares span types and still lacks a proposal.
Findings enter the EvidenceSet as derived items with full provenance — they
never set RESOLVED by themselves; the normal assessment decides their use.

Database discipline (root rule): all inputs are materialized and committed
before any GLiNER2/Jev call; results persist in a new short transaction.
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
    ContractFinding,
    NEED_LABELS,
    SpanVerdict,
    canon,
    derive_findings,
    verification_question,
)
from app.services.research.gliner.proposer import ProposalUnit, propose_spans

#: Run-level opt-in key in ExecutionAttempt.configuration_snapshot.
OPT_IN_KEY = "gliner_span_proposer"

#: Item provenance marker; needs with such an item are not re-proposed.
DERIVATION = "gliner_span_proposal"

#: Reverse label map so each proposal is verified against its own type.
LABEL_TO_TYPE = {label: span_type for span_type, label in NEED_LABELS.items()}


@dataclass(frozen=True)
class GlinerStepReport:
    needs_considered: int
    units_scanned: int
    inferences: int
    jev_calls: int
    findings_persisted: int


def is_opted_in(attempt: object) -> bool:
    snapshot = getattr(attempt, "configuration_snapshot", None) or {}
    return snapshot.get(OPT_IN_KEY) is True


def enabled_and_opted_in(attempt: object) -> bool:
    return settings.gliner_span_proposer.enabled and is_opted_in(attempt)


def _labels_for(need: object) -> tuple[str, ...]:
    span_types = getattr(need, "span_types", ()) or ()
    return tuple(NEED_LABELS[span_type] for span_type in span_types)[:3]


def _target_needs(plan: object, assessment: object) -> list[object]:
    insufficient = {
        row.research_need_id for row in assessment.need_assessments if not row.sufficient
    }
    return [
        need
        for need in plan.needs
        if need.id in insufficient and getattr(need, "span_types", None)
    ]


def _unit_texts(need: object, items: list[object]) -> tuple[ProposalUnit, ...]:
    units: list[ProposalUnit] = []
    seen: set[str] = set()
    for item in items:
        if item.research_need_id != need.id:
            continue
        if item.status != "found" or not item.excerpt:
            continue
        if item.provenance.get("derivation") == DERIVATION:
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
    choice = answer.get("choice")
    return SpanVerdict(
        span=span,
        need_type=need_type,
        prompt_version=str(question["prompt_version"]),
        choice=str(choice).upper() if choice else "UNCERTAIN",
        unit_id=unit.unit_id,
    )


async def _proposal_phase(
    jev: object,
    targets: list[object],
    units_by_need: dict[str, tuple[ProposalUnit, ...]],
) -> tuple[dict[str, list[ContractFinding]], int, int]:
    """GLiNER2 + Jev for every targeted need. No database access here."""
    findings_by_need: dict[str, list[ContractFinding]] = {}
    jev_calls = 0
    inferences = 0
    for need in targets:
        units = units_by_need[need.id]
        if not units:
            continue
        need_role = getattr(need, "span_role", "") or ""
        proposed = await propose_spans(units, _labels_for(need))
        inferences += 1
        by_unit = {entry.unit_id: entry for entry in proposed}
        for unit in units:
            entry = by_unit.get(unit.unit_id)
            if entry is None or not entry.proposals:
                continue
            verdicts: list[SpanVerdict] = []
            for proposal in entry.proposals[: settings.gliner_span_proposer.max_spans_per_unit]:
                need_type = LABEL_TO_TYPE.get(proposal.label)
                if need_type is None:
                    continue
                verdicts.append(
                    await _verify_span(
                        jev, unit=unit, need_type=need_type, span=proposal.span
                    )
                )
            jev_calls += len(verdicts)
            for need_type in dict.fromkeys(v.need_type for v in verdicts):
                scoped = [v for v in verdicts if v.need_type == need_type]
                findings_by_need.setdefault(need.id, []).extend(
                    derive_findings(
                        scoped,
                        need_type=need_type,
                        need_role=need_role,
                        unit_text=unit.text,
                    )
                )
    return findings_by_need, jev_calls, inferences


async def _persist_verified(
    config: object,
    targets: list[object],
    findings_by_need: dict[str, list[ContractFinding]],
) -> int:
    """Persist VERIFIED findings as derived evidence items (fresh session)."""
    from app.services.execution.service import add_evidence_items
    from app.services.research.models import research_evidence

    persisted = 0
    async with config.factory() as write_session:
        for need in targets:
            verified = [
                finding
                for finding in findings_by_need.get(need.id, [])
                if finding.state == "VERIFIED"
            ]
            if not verified:
                continue
            digest = hashlib.sha256(
                json.dumps(
                    [[finding.span, finding.value, finding.need_type] for finding in verified],
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()[:16]
            claims = []
            lines = []
            for finding in verified:
                predicate = NEED_LABELS.get(finding.need_type, finding.need_type)
                claims.append(
                    {
                        "id": hashlib.sha256(
                            f"{need.id}:{digest}:{canon(finding.span)}".encode()
                        ).hexdigest(),
                        "predicate": predicate,
                        "value": finding.span,
                        "derived": True,
                        "research_need_id": need.id,
                    }
                )
                lines.append(f"{predicate}: {finding.span}")
            await add_evidence_items(
                write_session,
                evidence_set_id=config.evidence_set_id,
                items=[
                    research_evidence(
                        research_need_id=need.id,
                        source_type="derived",
                        status="found",
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
                            "verified_spans": [
                                {
                                    "span": finding.span,
                                    "value": finding.value,
                                    "need_type": finding.need_type,
                                }
                                for finding in verified
                            ],
                            "derived_claims": claims,
                        },
                    )
                ],
            )
            persisted += 1
        await write_session.commit()
    return persisted


async def maybe_run_gliner_step(
    config: object,
    session: object,
    *,
    attempt: object,
    plan: object,
    assessment: object,
) -> GlinerStepReport | None:
    """Run the span-proposal step for incomplete needs; no-op when off.

    The caller's session is used only for the input phase and committed
    before any external call; persistence happens in a fresh session.
    Failures propagate — an enabled step never degrades silently.
    """
    if not enabled_and_opted_in(attempt):
        return None
    if assessment.result != "insufficient":
        return None
    targets = _target_needs(plan, assessment)
    if not targets:
        return None

    # Input phase: materialize units per need and release the connection.
    from app.services.execution.service import list_evidence_items

    items = await list_evidence_items(session, config.evidence_set_id)
    units_by_need = {need.id: _unit_texts(need, items) for need in targets}
    await session.commit()

    findings_by_need, jev_calls, inferences = await _proposal_phase(
        HttpJevSystemOne(), targets, units_by_need
    )
    record_gliner_inference(inferences)
    persisted = await _persist_verified(config, targets, findings_by_need)

    return GlinerStepReport(
        needs_considered=len(targets),
        units_scanned=sum(len(units_by_need[need.id]) for need in targets),
        inferences=inferences,
        jev_calls=jev_calls,
        findings_persisted=persisted,
    )
