"""External proposal phase: GLiNER2 span proposals + Jev verification.

Pure I/O against the model and Jev — no database access, no persistence.
The orchestrating step materializes inputs, calls this phase with no
connection held, and persists the outcome in a new short transaction.

Candidates omitted by an earlier truncation are retried FIRST on the next
run, so a later batch can resolve the earlier incompleteness instead of
inheriting usable evidence from an incomplete candidate picture. Truncation
is typed: dropping candidates because of the per-unit span cap, the per-need
Jev budget or the step Jev budget never masquerades as another cause.
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
    canon,
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
class PhaseInput:
    """Everything the external phase needs, materialized before it runs."""

    units_by_need: dict[str, tuple[ProposalUnit, ...]]
    retry_candidates: dict[str, list[dict[str, object]]]
    unit_texts: dict[str, str]


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
    unresolved: dict[str, list[dict[str, object]]] = field(default_factory=dict)


@dataclass(frozen=True)
class _NeedScan:
    verdicts: list[SpanVerdict]
    jev_calls: int
    reasons: frozenset[str]
    unprocessed: list[dict[str, object]]
    unresolved: list[dict[str, object]]


async def _verify_span(
    jev: object,
    *,
    unit_id: str,
    unit_text: str,
    need_type: str,
    span: str,
) -> SpanVerdict:
    question = verification_question(need_type, span)
    started = time.perf_counter()
    result = await jev.ask(
        state={"text": unit_text},
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
            f"in unit {unit_id!r}"
        )
    return SpanVerdict(
        span=span,
        need_type=need_type,
        prompt_version=str(question["prompt_version"]),
        choice=choice,
        unit_id=unit_id,
        unit_text=unit_text,
        role=operational_role(span, unit_text),
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


async def _retry_candidates(
    jev: object,
    need: object,
    candidates: list[dict[str, object]],
    unit_texts: dict[str, str],
    *,
    step_calls: int,
) -> tuple[list[SpanVerdict], list[dict[str, object]], set[str], int]:
    """Verify candidates an earlier truncation left unprocessed."""
    verdicts: list[SpanVerdict] = []
    unresolved: list[dict[str, object]] = []
    reasons: set[str] = set()
    calls = 0
    per_need_budget = settings.gliner_span_proposer.max_jev_calls_per_need
    step_budget = settings.gliner_span_proposer.max_jev_calls_per_step
    for candidate in candidates:
        unit_id = str(candidate.get("unit_id") or "")
        span = str(candidate.get("span") or "")
        label = str(candidate.get("label") or "")
        need_type = LABEL_TO_TYPE.get(label)
        if need_type is None or unit_id not in unit_texts or not span:
            # An unverifiable leftover keeps the need incomplete (fail-safe).
            unresolved.append(dict(candidate))
            continue
        if calls >= per_need_budget or step_calls + calls >= step_budget:
            reason = (
                PER_NEED_JEV_BUDGET
                if calls >= per_need_budget
                else STEP_JEV_BUDGET
            )
            reasons.add(reason)
            unresolved.append(dict(candidate))
            continue
        verdicts.append(
            await _verify_span(
                jev,
                unit_id=unit_id,
                unit_text=unit_texts[unit_id],
                need_type=need_type,
                span=span,
            )
        )
        calls += 1
    return verdicts, unresolved, reasons, calls


async def _scan_need(
    jev: object,
    need: object,
    *,
    phase: PhaseInput,
    step_calls: int,
) -> _NeedScan:
    """Scan one need: retried candidates, then this batch's units."""
    units = phase.units_by_need[need.id]
    by_unit = {
        entry.unit_id: entry
        for entry in await propose_spans(units, _labels_for(need))
    }
    retry_verdicts, unresolved, reasons, need_calls = await _retry_candidates(
        jev,
        need,
        phase.retry_candidates.get(need.id, []),
        phase.unit_texts,
        step_calls=step_calls,
    )
    verdicts: list[SpanVerdict] = list(retry_verdicts)
    seen = {
        (verdict.unit_id, verdict.need_type, canon(verdict.span))
        for verdict in retry_verdicts
    }
    unprocessed: list[dict[str, object]] = []
    per_need_budget = settings.gliner_span_proposer.max_jev_calls_per_need
    step_budget = settings.gliner_span_proposer.max_jev_calls_per_step
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
            # A span proposed for several declared types is verified per type:
            # the Jev question and the contract differ per need_type.
            key = (unit.unit_id, need_type, canon(proposal.span))
            if key in seen:
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
            seen.add(key)
            verdicts.append(
                await _verify_span(
                    jev,
                    unit_id=unit.unit_id,
                    unit_text=unit.text,
                    need_type=need_type,
                    span=proposal.span,
                )
            )
            need_calls += 1
    return _NeedScan(
        verdicts=verdicts,
        jev_calls=need_calls,
        reasons=frozenset(reasons),
        unprocessed=unprocessed,
        unresolved=unresolved,
    )


async def run_proposal_phase(
    jev: object,
    targets: list[object],
    phase: PhaseInput,
) -> ProposalPhaseOutcome:
    """GLiNER2 + Jev for every targeted need. No database access here."""
    verdicts_by_need: dict[str, list[SpanVerdict]] = {}
    proposed_needs: set[str] = set()
    truncation_reasons: dict[str, frozenset[str]] = {}
    unprocessed: dict[str, list[dict[str, object]]] = {}
    unresolved: dict[str, list[dict[str, object]]] = {}
    units_total = 0
    jev_total = 0
    step_budget = settings.gliner_span_proposer.max_jev_calls_per_step
    for need in targets:
        if jev_total >= step_budget:
            break
        units_total += len(phase.units_by_need[need.id])
        scan = await _scan_need(jev, need, phase=phase, step_calls=jev_total)
        proposed_needs.add(need.id)
        verdicts_by_need[need.id] = scan.verdicts
        jev_total += scan.jev_calls
        if scan.reasons:
            truncation_reasons[need.id] = scan.reasons
        if scan.unprocessed:
            unprocessed[need.id] = scan.unprocessed
        if scan.unresolved:
            unresolved[need.id] = scan.unresolved
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
        unresolved=unresolved,
    )
