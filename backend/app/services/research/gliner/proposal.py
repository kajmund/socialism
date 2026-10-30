"""External proposal phase: GLiNER2 span proposals + Jev verification.

Pure I/O against the model and Jev — no database access, no persistence.
The orchestrating step materializes inputs, calls this phase with no
connection held, and persists the outcome in a new short transaction.

Truncation is typed: dropping candidates because of the per-unit span cap,
the per-need Jev budget or the step Jev budget never masquerades as another
cause, and a truncated need never yields usable evidence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.config import settings
from app.observability.research import record_jev_call
from app.services.research.gliner.contract import (
    LABEL_TO_TYPE,
    NEED_LABELS,
    SpanVerdict,
    operational_role,
    verification_question,
)
from app.services.research.gliner.proposer import ProposalUnit, propose_spans

#: Schema-valid Jev choices. Anything else is a loud schema error.
JEV_CHOICES = frozenset({"YES", "NO", "UNCERTAIN"})

#: Typed truncation reasons carried into the report and provenance.
SPAN_CAP = "span_cap"
PER_NEED_JEV_BUDGET = "per_need_jev_budget"
STEP_JEV_BUDGET = "step_jev_budget"


class GlinerStepError(Exception):
    """The enabled step failed. Research fails closed — never silently skips."""


@dataclass(frozen=True)
class ProposalPhaseStats:
    units: int
    jev_calls: int
    truncation_reasons: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ProposalPhaseOutcome:
    verdicts_by_need: dict[str, list[SpanVerdict]] = field(default_factory=dict)
    stats: ProposalPhaseStats = ProposalPhaseStats(0, 0)
    proposed_needs: frozenset[str] = frozenset()
    truncation_reasons: dict[str, frozenset[str]] = field(default_factory=dict)
    unprocessed: dict[str, list[dict[str, object]]] = field(default_factory=dict)


@dataclass(frozen=True)
class _NeedScan:
    verdicts: list[SpanVerdict]
    jev_calls: int
    reasons: frozenset[str]
    unprocessed: list[dict[str, object]]


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
        role=operational_role(span, unit.text),
        role_locked=True,
    )


def _labels_for(need: object) -> tuple[str, ...]:
    """All declared span types are sent — never silently capped."""
    span_types = getattr(need, "span_types", ()) or ()
    return tuple(NEED_LABELS[span_type] for span_type in span_types)


def _truncation_reason(
    *,
    unit_considered: int,
    need_calls: int,
    step_calls: int,
    per_need_budget: int,
    step_budget: int,
) -> str:
    if unit_considered >= settings.gliner_span_proposer.max_spans_per_unit:
        return SPAN_CAP
    if need_calls >= per_need_budget:
        return PER_NEED_JEV_BUDGET
    if step_calls >= step_budget:
        return STEP_JEV_BUDGET
    return ""


async def _proposals_for_need(need: object, units: tuple[ProposalUnit, ...]) -> dict:
    proposed = await propose_spans(units, _labels_for(need))
    return {entry.unit_id: entry for entry in proposed}


async def _scan_need(
    jev: object,
    need: object,
    units: tuple[ProposalUnit, ...],
    *,
    step_calls: int,
) -> _NeedScan:
    """Scan one need: per-unit span cap, typed truncation, Jev verification."""
    by_unit = await _proposals_for_need(need, units)
    verdicts: list[SpanVerdict] = []
    reasons: set[str] = set()
    unprocessed: list[dict[str, object]] = []
    per_need_budget = settings.gliner_span_proposer.max_jev_calls_per_need
    step_budget = settings.gliner_span_proposer.max_jev_calls_per_step
    need_calls = 0
    for unit in units:
        entry = by_unit.get(unit.unit_id)
        if entry is None or not entry.proposals:
            continue
        # The span cap applies PER UNIT: two units at exactly the cap are not
        # truncation.
        unit_considered = 0
        for proposal in entry.proposals:
            need_type = LABEL_TO_TYPE.get(proposal.label)
            if need_type is None:
                continue
            reason = _truncation_reason(
                unit_considered=unit_considered,
                need_calls=need_calls,
                step_calls=step_calls + need_calls,
                per_need_budget=per_need_budget,
                step_budget=step_budget,
            )
            if reason:
                reasons.add(reason)
                unprocessed.append(
                    {
                        "span": proposal.span,
                        "label": proposal.label,
                        "unit_id": unit.unit_id,
                    }
                )
                continue
            unit_considered += 1
            verdicts.append(
                await _verify_span(
                    jev, unit=unit, need_type=need_type, span=proposal.span
                )
            )
            need_calls += 1
    return _NeedScan(
        verdicts=verdicts,
        jev_calls=need_calls,
        reasons=frozenset(reasons),
        unprocessed=unprocessed,
    )


async def run_proposal_phase(
    jev: object,
    targets: list[object],
    units_by_need: dict[str, tuple[ProposalUnit, ...]],
) -> ProposalPhaseOutcome:
    """GLiNER2 + Jev for every targeted need. No database access here."""
    verdicts_by_need: dict[str, list[SpanVerdict]] = {}
    proposed_needs: set[str] = set()
    truncation_reasons: dict[str, frozenset[str]] = {}
    unprocessed: dict[str, list[dict[str, object]]] = {}
    units_total = 0
    jev_total = 0
    step_budget = settings.gliner_span_proposer.max_jev_calls_per_step
    for need in targets:
        if jev_total >= step_budget:
            break
        units = units_by_need[need.id]
        units_total += len(units)
        scan = await _scan_need(jev, need, units, step_calls=jev_total)
        proposed_needs.add(need.id)
        verdicts_by_need[need.id] = scan.verdicts
        jev_total += scan.jev_calls
        if scan.reasons:
            truncation_reasons[need.id] = scan.reasons
        if scan.unprocessed:
            unprocessed[need.id] = scan.unprocessed
    all_reasons = frozenset(
        reason for reasons in truncation_reasons.values() for reason in reasons
    )
    return ProposalPhaseOutcome(
        verdicts_by_need=verdicts_by_need,
        stats=ProposalPhaseStats(
            units=units_total,
            jev_calls=jev_total,
            truncation_reasons=all_reasons,
        ),
        proposed_needs=frozenset(proposed_needs),
        truncation_reasons=truncation_reasons,
        unprocessed=unprocessed,
    )
