"""Opt-in GLiNER2 span-proposal step for incomplete research needs.

The tool is SWE's choice, never a mandatory step: it runs only when the
global switch is on, the research run opted in, the assessment is
insufficient, and a need declares span types and still lacks a proposal for
the CURRENT evidence. Findings enter the EvidenceSet as derived items with
full provenance — they never set RESOLVED by themselves; the normal
assessment decides their use.

The step only orchestrates: it materializes inputs, calls the external
proposal phase with no database connection held, then persists findings and
refreshes the wave assessment (see ``persistence`` and ``proposal``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.config import settings
from app.observability.research import record_gliner_inference
from app.services.research.gliner.contract import (
    DERIVATION,
    NEED_LABELS,
)
from app.services.research.gliner.persistence import (
    persist_findings_and_invalidate,
    refresh_assessment,
)
from app.jev.system import HttpJevSystemOne
from app.services.research.gliner.proposal import (
    GlinerStepError,
    run_proposal_phase,
)
from app.services.research.gliner.proposer import ProposalUnit

#: Run-level opt-in key in ExecutionAttempt.configuration_snapshot.
OPT_IN_KEY = "gliner_span_proposer"

#: Re-exported for callers and tests that assert typed step failures.
__all__ = ["GlinerStepError", "maybe_run_gliner_step"]


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


def is_opted_in(attempt: object) -> bool:
    snapshot = getattr(attempt, "configuration_snapshot", None) or {}
    return snapshot.get(OPT_IN_KEY) is True


def enabled_and_opted_in(attempt: object) -> bool:
    return settings.gliner_span_proposer.enabled and is_opted_in(attempt)


def _labels_for(need: object) -> tuple[str, ...]:
    """All declared span types are sent — never silently capped."""
    span_types = getattr(need, "span_types", ()) or ()
    return tuple(NEED_LABELS[span_type] for span_type in span_types)


def _input_fingerprint(units: tuple[ProposalUnit, ...], labels: tuple[str, ...]) -> str:
    """Stable identity of the inputs a proposal run would see.

    New evidence (or new labels/model) changes the fingerprint and therefore
    may trigger a new run; identical inputs never re-run.
    """
    payload = json.dumps(
        {
            "units": [
                [unit.unit_id, hashlib.sha256(unit.text.encode()).hexdigest()]
                for unit in units
            ],
            "labels": list(labels),
            "model": settings.gliner_span_proposer.model,
            "threshold": settings.gliner_span_proposer.threshold,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _prior_fingerprints(need_id: str, items: list[object]) -> set[str]:
    """Fingerprints of earlier proposal runs for this need."""
    fingerprints: set[str] = set()
    for item in items:
        provenance = item.provenance or {}
        if item.research_need_id != need_id:
            continue
        if provenance.get("derivation") != DERIVATION:
            continue
        fingerprint = str(provenance.get("input_fingerprint") or "")
        if fingerprint:
            fingerprints.add(fingerprint)
    return fingerprints


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


def _assessment_draft(assessment: object) -> object:
    """Persisted assessments store JSON rows; convert before reading fields."""
    from app.services.research.assessment import assessment_draft_from_row

    return assessment_draft_from_row(assessment)


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
    findings are persisted and scored, or None when the step did not run. The
    caller's session is used only for the input phase and committed before any
    external call. Failures propagate — an enabled step never degrades silently.
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
    from app.services.research.followup import next_assessment_pass

    items = await list_evidence_items(session, config.evidence_set_id)
    units_by_need = {need.id: _unit_texts(need, items) for need in targets}
    fingerprints: dict[str, str] = {}
    pending: list[object] = []
    for need in targets:
        units = units_by_need[need.id]
        if not units:
            continue
        fingerprint = _input_fingerprint(units, _labels_for(need))
        if fingerprint in _prior_fingerprints(need.id, items):
            continue
        fingerprints[need.id] = fingerprint
        pending.append(need)
    if not pending:
        return None
    await session.commit()

    outcome = await run_proposal_phase(HttpJevSystemOne(), pending, units_by_need)
    record_gliner_inference(outcome.stats.units)
    persisted_ids = await persist_findings_and_invalidate(
        config,
        pending,
        outcome,
        fingerprints=fingerprints,
        attempt_id=attempt.id,
        assessment_pass=next_assessment_pass(wave),
    )
    if not persisted_ids:
        return None
    refreshed = await refresh_assessment(
        config, attempt, plan=plan, wave=wave, persisted_ids=persisted_ids
    )
    return GlinerStepResult(
        assessment=refreshed,
        report=GlinerStepReport(
            needs_considered=len(pending),
            units_scanned=outcome.stats.units,
            inferences=outcome.stats.units,
            jev_calls=outcome.stats.jev_calls,
            findings_persisted=len(persisted_ids),
            jev_budget_truncated=outcome.stats.jev_budget_truncated,
        ),
    )
