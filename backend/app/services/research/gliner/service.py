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


def _input_fingerprint(items: list[object], labels: tuple[str, ...]) -> str:
    """Stable identity of the FULL qualified input set for a need.

    New evidence (or new labels/model) changes the fingerprint even when a
    batch boundary hides the new item from the current run.
    """
    payload = json.dumps(
        {
            "units": [
                [item.id, hashlib.sha256((item.excerpt or "").encode()).hexdigest()]
                for item in items
            ],
            "labels": list(labels),
            "model": settings.gliner_span_proposer.model,
            "threshold": settings.gliner_span_proposer.threshold,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _need_ids_for(item: object) -> tuple[str, ...]:
    """Needs that share a stored passage (deduplicated evidence).

    Shared passages are linked through EvidenceSetItemNeed; the primary need
    column is only a fallback.
    """
    links = tuple(link.research_need_id for link in (item.need_links or ()))
    if links:
        return links
    primary = item.research_need_id
    return (primary,) if primary else ()


def _eligible_items(need: object, items: list[object]) -> list[object]:
    """All evidence items this need may scan, in deterministic order."""
    eligible = [
        item
        for item in items
        if need.id in _need_ids_for(item)
        and item.status == "found"
        and item.excerpt
        and (item.provenance or {}).get("derivation") != DERIVATION
    ]
    return sorted(eligible, key=lambda item: (item.ordinal or 0, item.id))


def _processed_unit_ids(need: object, items: list[object]) -> set[str]:
    """Unit ids already scanned by earlier proposal runs for this need."""
    processed: set[str] = set()
    for item in items:
        provenance = item.provenance or {}
        if provenance.get("derivation") != DERIVATION:
            continue
        if need.id not in _need_ids_for(item):
            continue
        processed.update(str(unit_id) for unit_id in provenance.get("processed_units") or [])
    return processed


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


def _batch_units(eligible: list[object], processed: set[str]) -> tuple[ProposalUnit, ...]:
    """Next deterministic batch of not-yet-scanned units."""
    limit = settings.gliner_span_proposer.max_units_per_need
    units: list[ProposalUnit] = []
    for item in eligible:
        if item.id in processed:
            continue
        units.append(
            ProposalUnit(
                unit_id=item.id,
                text=item.excerpt[: settings.gliner_span_proposer.max_excerpt_chars],
            )
        )
        if len(units) >= limit:
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
    pending: list[object] = []
    units_by_need: dict[str, tuple[ProposalUnit, ...]] = {}
    fingerprints: dict[str, str] = {}
    processed_units: dict[str, list[str]] = {}
    for need in targets:
        eligible = _eligible_items(need, items)
        if not eligible:
            continue
        batch = _batch_units(eligible, _processed_unit_ids(need, items))
        if not batch:
            continue
        # The fingerprint covers the FULL qualified input set, so late evidence
        # is visible even when a batch boundary hides it from this run.
        fingerprints[need.id] = _input_fingerprint(eligible, _labels_for(need))
        processed_units[need.id] = [unit.unit_id for unit in batch]
        units_by_need[need.id] = batch
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
        processed_units=processed_units,
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
