"""External proposal phase: GLiNER2 span proposals + Jev verification.

Pure I/O against the model and Jev — no database access, no persistence.
The orchestrating step materializes inputs, calls this phase with no
connection held, and persists the outcome in a new short transaction.
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
    derive_findings,
    verification_question,
)
from app.services.research.gliner.proposer import ProposalUnit, propose_spans

#: Schema-valid Jev choices. Anything else is a loud schema error.
JEV_CHOICES = frozenset({"YES", "NO", "UNCERTAIN"})


class GlinerStepError(Exception):
    """The enabled step failed. Research fails closed — never silently skips."""


@dataclass(frozen=True)
class ProposalPhaseStats:
    units: int
    jev_calls: int
    jev_budget_truncated: bool


@dataclass(frozen=True)
class ProposalPhaseOutcome:
    findings_by_need: dict[str, list[object]] = field(default_factory=dict)
    stats: ProposalPhaseStats = ProposalPhaseStats(0, 0, False)
    proposed_needs: frozenset[str] = frozenset()
    truncated_needs: frozenset[str] = frozenset()
    unprocessed: dict[str, list[dict[str, object]]] = field(default_factory=dict)


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


def _labels_for(need: object) -> tuple[str, ...]:
    """All declared span types are sent — never silently capped."""
    span_types = getattr(need, "span_types", ()) or ()
    return tuple(NEED_LABELS[span_type] for span_type in span_types)


async def run_proposal_phase(
    jev: object,
    targets: list[object],
    units_by_need: dict[str, tuple[ProposalUnit, ...]],
) -> ProposalPhaseOutcome:
    """GLiNER2 + Jev for every targeted need. No database access here."""
    findings_by_need: dict[str, list[object]] = {}
    proposed_needs: set[str] = set()
    truncated_needs: set[str] = set()
    unprocessed: dict[str, list[dict[str, object]]] = {}
    units_total = 0
    jev_total = 0
    per_need_budget = settings.gliner_span_proposer.max_jev_calls_per_need
    step_budget = settings.gliner_span_proposer.max_jev_calls_per_step
    for need in targets:
        if jev_total >= step_budget:
            break
        units = units_by_need[need.id]
        units_total += len(units)
        need_role = getattr(need, "span_role", "") or ""
        proposed = await propose_spans(units, _labels_for(need))
        proposed_needs.add(need.id)
        by_unit = {entry.unit_id: entry for entry in proposed}
        need_verdicts: list[SpanVerdict] = []
        need_calls = 0
        truncated_here = False
        for unit in units:
            entry = by_unit.get(unit.unit_id)
            if entry is None or not entry.proposals:
                continue
            for proposal in entry.proposals[: settings.gliner_span_proposer.max_spans_per_unit]:
                need_type = LABEL_TO_TYPE.get(proposal.label)
                if need_type is None:
                    continue
                if need_calls >= per_need_budget or jev_total >= step_budget:
                    truncated_here = True
                    truncated_needs.add(need.id)
                    unprocessed.setdefault(need.id, []).append(
                        {
                            "span": proposal.span,
                            "label": proposal.label,
                            "unit_id": unit.unit_id,
                        }
                    )
                    continue
                need_verdicts.append(
                    await _verify_span(
                        jev, unit=unit, need_type=need_type, span=proposal.span
                    )
                )
                need_calls += 1
                jev_total += 1
        # Aggregate across every scanned unit: competing values in different
        # units must still collide into one AMBIGUOUS finding.
        for need_type in dict.fromkeys(v.need_type for v in need_verdicts):
            scoped = [v for v in need_verdicts if v.need_type == need_type]
            findings_by_need.setdefault(need.id, []).extend(
                derive_findings(scoped, need_type=need_type, need_role=need_role)
            )
        if truncated_here and jev_total >= step_budget:
            break
    return ProposalPhaseOutcome(
        findings_by_need=findings_by_need,
        stats=ProposalPhaseStats(
            units=units_total,
            jev_calls=jev_total,
            jev_budget_truncated=bool(truncated_needs),
        ),
        proposed_needs=frozenset(proposed_needs),
        truncated_needs=frozenset(truncated_needs),
        unprocessed=unprocessed,
    )
