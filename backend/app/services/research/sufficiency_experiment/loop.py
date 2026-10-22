"""SWE-driven sufficiency loop. Same handler-object pattern as SweResearchLoop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any


from app.jev.system import JevSystemOne
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentDraft,
    can_assess_programmatically,
    group_evidence_for_review,
    programmatic_assessment,
    sanitize_assessment_draft,
)
from app.services.research.models import ResearchPlan
from app.services.research.sufficiency_experiment.aggregate import aggregate_plan
from app.services.research.sufficiency_experiment.emit import draft_from_aggregations
from app.services.research.sufficiency_experiment.jev_eval import (
    evaluate_job,
    evaluation_jobs,
    quality_inputs,
)
from app.services.research.sufficiency_experiment.narrative import (
    NarrativeFn,
    run_narrative,
)
from app.services.research.sufficiency_experiment.obligations import present_source_types
from app.services.research.sufficiency_experiment.quality import quality_gate
from app.services.research.sufficiency_experiment.route import (
    decide_route,
    resolve_conflict,
    route_state,
)
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    EvidencePassage,
    ExperimentConfig,
    ExperimentReport,
    ExperimentStatus,
    GateInputs,
    NeedAggregation,
    PassageEvaluation,
    QualityDecision,
    RouteDecision,
    concat_source_chars,
)
from app.services.research.sufficiency_experiment.workflow import (
    compile_sufficiency_workflow,
)
from app.swe.runtime import RunResult, WorkflowResources, WorkflowRunner
from app.swe.runtime_dispatch import Handler


class SufficiencyLoop:
    """One SWE run that judges a complete EvidenceSet."""

    def __init__(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
        *,
        client: JevSystemOne,
        config: ExperimentConfig,
        narrative: NarrativeFn | None = None,
        live_measurement: str = "not_run",
    ) -> None:
        self._plan = plan
        self._evidence = list(evidence)
        self._client = client
        self._config = config
        self._narrative = narrative
        self._live_measurement = live_measurement
        self._started = perf_counter()
        self._groups = group_evidence_for_review(evidence)
        self._passages: list[EvidencePassage] = []
        self._jobs: list[dict[str, object]] = []
        self._items = quality_inputs(evidence)
        self._evaluations: list[PassageEvaluation] = []
        self._aggregations: tuple[NeedAggregation, ...] = ()
        self._quality: QualityDecision | None = None
        self._route: RouteDecision | None = None
        self._addressed: list[str] = []
        self._subworkflow_rounds = 0
        self._narrative_rounds = 0
        self._draft: ResearchAssessmentDraft | None = None
        self._status: ExperimentStatus = "failed"
        self._failure: str | None = None
        self._jev_calls = 0
        self._llm_calls = 0
        self._source_chars = sum(len(item.excerpt or "") for item in evidence)
        self._judged_chars = 0
        self.report: ExperimentReport | None = None
        self.handlers: dict[str, Handler] = {
            "sufficiency.prepare": self._prepare,
            "sufficiency.evaluate_one": self._evaluate_one,
            "sufficiency.aggregate": self._aggregate,
            "sufficiency.route": self._decide_route,
            "sufficiency.resolve": self._resolve,
            "sufficiency.narrative": self._run_narrative,
            "sufficiency.emit": self._emit,
        }

    async def run(self, *, run_id: str | None = None) -> RunResult:
        runner = WorkflowRunner(
            compile_sufficiency_workflow(self._config.jev_concurrency),
            self.handlers,
            resources=WorkflowResources(),
            concurrency=self._config.jev_concurrency,
        )
        result = await runner.run({}, run_id=run_id)
        events = tuple(str(event.get("type") or "") for event in result.events)
        if result.status != "completed":
            self._status = "failed"
            self._failure = result.status
            self._draft = self._fail_closed_draft()
            self.report = self._build_report(result.run_id, events)
            return result
        if self.report is None:
            self.report = self._build_report(result.run_id, events)
        else:
            self.report = ExperimentReport(
                **{
                    **self.report.__dict__,
                    "swe_events": events,
                    "swe_run_id": result.run_id,
                }
            )
        return result

    async def _prepare(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        if can_assess_programmatically(self._plan, self._evidence):
            self._draft = programmatic_assessment(self._plan, self._evidence)
            self._status = "sufficient" if self._draft.result == "sufficient" else "insufficient"
            self._judged_chars = self._source_chars
            self._quality = quality_gate(
                (),
                GateInputs(span_coverage=1.0),
                self._config,
            )
            return {"done": True, "jobs": []}
        self._passages = segment_evidence(
            self._evidence, max_chars=self._config.max_passage_chars
        )
        self._jobs = evaluation_jobs(self._plan.needs, self._passages)
        self._judged_chars = concat_source_chars(self._passages)
        return {"done": False, "jobs": self._jobs}

    async def _evaluate_one(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        job = dict(payload["item"])
        if self._jev_calls >= self._config.max_jev_calls:
            self._failure = "budget_exhausted"
            raise RuntimeError("Jev call budget exhausted")
        row = await evaluate_job(
            job,
            self._client,
            self._config,
            quality_item=self._items.get(str(job["evidence_id"])),
        )
        self._jev_calls += 1
        self._evaluations.append(row)
        return {"job_id": row.job_id, "error": row.error}

    async def _aggregate(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        present = {
            need.id: present_source_types(need, self._evidence)
            for need in self._plan.needs
        }
        rows = aggregate_plan(
            self._plan,
            self._evaluations,
            config=self._config,
            addressed_conflicts=self._addressed,
            source_types_by_id=present,
        )
        self._aggregations = tuple(rows)
        required = {str(job["job_id"]) for job in self._jobs}
        seen = {row.job_id for row in self._evaluations}
        missing = tuple(sorted(required - seen))
        errors = tuple(row.job_id for row in self._evaluations if row.error)
        coverage = 1.0 if self._source_chars == 0 else self._judged_chars / self._source_chars
        self._quality = quality_gate(
            self._aggregations,
            GateInputs(
                span_coverage=coverage,
                missing_evaluations=missing,
                evaluation_errors=errors,
                budget_exhausted=self._failure == "budget_exhausted",
                narrative_rounds=self._narrative_rounds,
                subworkflow_rounds=self._subworkflow_rounds,
            ),
            self._config,
        )
        return {
            "need_count": len(self._aggregations),
            "allows_sufficient": self._quality.allows_sufficient,
        }

    async def _decide_route(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        quality = self._require_quality()
        self._route = await decide_route(
            self._client,
            self._config,
            self._aggregations,
            quality,
            state=route_state(self._aggregations, quality),
        )
        self._jev_calls += 1
        return {
            "choice": self._route.choice,
            "finish": self._route.choice == "FINISH",
            "run_subworkflow": self._route.choice == "RUN_SUBWORKFLOW",
            "escalate": self._route.choice == "ESCALATE_NARRATIVE",
        }

    async def _resolve(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        newly = resolve_conflict(
            self._aggregations, self._evaluations, config=self._config
        )
        self._addressed.extend(item for item in newly if item not in self._addressed)
        self._subworkflow_rounds += 1
        return {"addressed": list(newly), "round": self._subworkflow_rounds}

    async def _run_narrative(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        if self._narrative is None:
            self._status = "uncertain"
            self._failure = "narrative_unbound"
            return {"ran": False}
        self._draft, _events = await run_narrative(
            self._plan,
            self._aggregations,
            config=self._config,
            registry={},
            completer=self._narrative,
            depth=self._narrative_rounds,
        )
        self._narrative_rounds += 1
        self._llm_calls += 1
        self._status = "sufficient" if self._draft.result == "sufficient" else "insufficient"
        return {"ran": True}

    async def _emit(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        if self._draft is None:
            if self._failure != "narrative_unbound":
                self._status = self._emit_status()
            self._draft = draft_from_aggregations(
                self._aggregations,
                status=self._status,
                considered=[item.evidence_id for item in self._evidence],
                reasons=self._quality.reasons if self._quality else (),
            )
        self._draft = sanitize_assessment_draft(
            self._draft, plan=self._plan, evidence=self._evidence
        )
        if self._draft.result != "sufficient" and self._status == "sufficient":
            self._status = "uncertain"
            self._failure = "sanitize_rejected_sufficient"
        self.report = self._build_report("", ())
        return {"status": self._status}

    def _emit_status(self) -> ExperimentStatus:
        quality = self._quality
        if quality is None:
            return "failed"
        if self._failure == "budget_exhausted":
            return "failed"
        if quality.allows_sufficient and all(row.sufficient for row in self._aggregations):
            return "sufficient"
        if any(row.unknown_requirements or row.unresolved_conflicts for row in self._aggregations):
            return "uncertain"
        if quality.budget_exhausted or quality.missing_evaluations or quality.omitted_evidence_ids:
            return "uncertain"
        return "insufficient"

    def _require_quality(self) -> QualityDecision:
        if self._quality is None:
            raise RuntimeError("route ran before aggregate")
        return self._quality

    def _fail_closed_draft(self) -> ResearchAssessmentDraft:
        return draft_from_aggregations(
            self._aggregations,
            status="failed",
            considered=[item.evidence_id for item in self._evidence],
            reasons=(self._failure or "swe_failed",),
        )

    def _build_report(self, run_id: str, events: tuple[str, ...]) -> ExperimentReport:
        draft = self._draft or self._fail_closed_draft()
        quality = self._quality or quality_gate(
            self._aggregations,
            GateInputs(span_coverage=0.0, budget_exhausted=True),
            self._config,
        )
        return ExperimentReport(
            draft=sanitize_assessment_draft(draft, plan=self._plan, evidence=self._evidence),
            status=self._status,
            passages=tuple(self._passages),
            evaluations=tuple(self._evaluations),
            aggregations=self._aggregations,
            quality=quality,
            route=self._route,
            swe_events=events,
            swe_run_id=run_id,
            jev_calls=self._jev_calls,
            llm_calls=self._llm_calls,
            latency_ms=(perf_counter() - self._started) * 1000,
            judged_chars=self._judged_chars,
            source_chars=self._source_chars,
            failure_mode=self._failure,
            live_measurement=self._live_measurement,
        )
