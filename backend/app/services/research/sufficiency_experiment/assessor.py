"""Opt-in complete-EvidenceSet assessor. Not used by production research."""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter

from app.jev.system import JevSystemOne
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentDraft,
    can_assess_programmatically,
    programmatic_assessment,
    sanitize_assessment_draft,
)
from app.services.research.models import ResearchPlan
from app.services.research.sufficiency_experiment.aggregate import aggregate_plan
from app.services.research.sufficiency_experiment.jev_eval import (
    evaluate_jobs,
    evaluation_jobs,
)
from app.services.research.sufficiency_experiment.narrative import (
    NarrativeFn,
    draft_from_aggregations,
    run_narrative,
)
from app.services.research.sufficiency_experiment.quality import quality_gate
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    ExperimentReport,
    ProvenanceEvent,
    concat_source_chars,
)


async def run_experiment(
    plan: ResearchPlan,
    evidence: Sequence[AssessableEvidence],
    *,
    client: JevSystemOne,
    config: ExperimentConfig | None = None,
    narrative: NarrativeFn | None = None,
    registry: dict | None = None,
) -> ExperimentReport:
    started = perf_counter()
    settings = config or ExperimentConfig()
    if can_assess_programmatically(plan, evidence):
        draft = programmatic_assessment(plan, evidence)
        source = sum(len(item.excerpt or "") for item in evidence)
        return ExperimentReport(
            draft=sanitize_assessment_draft(draft, plan=plan, evidence=evidence),
            passages=(),
            evaluations=(),
            aggregations=(),
            quality=quality_gate(
                (),
                coverage=1.0,
                omitted_evidence_ids=(),
                recursion_depth=0,
                config=settings,
                jev_requires_narrative=False,
            ),
            latency_ms=(perf_counter() - started) * 1000,
            judged_chars=source,
            source_chars=source,
        )
    passages = segment_evidence(evidence, max_chars=settings.max_passage_chars)
    jobs = evaluation_jobs(plan, passages)
    evaluations = await evaluate_jobs(jobs, plan, client, settings)
    aggregations = aggregate_plan(plan, evaluations)
    judged = concat_source_chars(passages)
    source = sum(len(item.excerpt or "") for item in evidence)
    coverage = 1.0 if source == 0 else judged / source
    quality = quality_gate(
        aggregations,
        coverage=coverage,
        omitted_evidence_ids=(),
        recursion_depth=0,
        config=settings,
        jev_requires_narrative=any(row.needs_narrative for row in aggregations),
    )
    provenance: list[ProvenanceEvent] = []
    llm_calls = 0
    considered = [item.evidence_id for item in evidence]
    if quality.escalate:
        if narrative is None:
            raise RuntimeError("narrative escalation required but no completer was bound")
        draft, events = await run_narrative(
            plan,
            aggregations,
            config=settings,
            registry=registry or {},
            completer=narrative,
            depth=0,
        )
        provenance.extend(events)
        llm_calls = 1
    else:
        draft = draft_from_aggregations(aggregations, considered=considered)
    return ExperimentReport(
        draft=sanitize_assessment_draft(draft, plan=plan, evidence=evidence),
        passages=tuple(passages),
        evaluations=tuple(evaluations),
        aggregations=tuple(aggregations),
        quality=quality,
        provenance=tuple(provenance),
        jev_calls=len(evaluations),
        llm_calls=llm_calls,
        latency_ms=(perf_counter() - started) * 1000,
        judged_chars=judged,
        source_chars=source,
    )


class ExperimentResearchAssessor:
    """ResearchAssessor that never truncates the EvidenceSet."""

    def __init__(
        self,
        *,
        client: JevSystemOne,
        config: ExperimentConfig | None = None,
        narrative: NarrativeFn | None = None,
    ) -> None:
        self._client = client
        self._config = config or ExperimentConfig()
        self._narrative = narrative

    async def assess(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchAssessmentDraft:
        report = await run_experiment(
            plan,
            evidence,
            client=self._client,
            config=self._config,
            narrative=self._narrative,
        )
        return report.draft
