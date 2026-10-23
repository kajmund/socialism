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
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.research.models import ResearchPlan
from app.services.research.sufficiency_experiment.aggregate import aggregate_plan
from app.services.research.sufficiency_experiment.claims import (
    extract_claim_candidates,
)
from app.services.research.sufficiency_experiment.coverage import (
    build_coverage_report,
)
from app.services.research.sufficiency_experiment.emit import draft_from_aggregations
from app.services.research.sufficiency_experiment.jev_eval import (
    evaluate_job,
    evaluation_jobs,
    quality_inputs,
)
from app.services.research.sufficiency_experiment.narrative_gap import (
    NarrativeGapFn,
    build_gap_payload,
    run_gap_review,
)
from app.services.research.sufficiency_experiment.narrative import (
    NarrativeFn,
    run_narrative,
)
from app.services.research.sufficiency_experiment.obligations import present_source_types
from app.services.research.sufficiency_experiment.pair_eval import (
    evaluate_pair,
    merge_pair_conflicts,
    pair_coverage,
)
from app.services.research.sufficiency_experiment.pairs import select_ordered_pairs
from app.services.research.sufficiency_experiment.quality import quality_gate
from app.services.research.sufficiency_experiment.route import (
    decide_route,
    route_state,
    status_from_route,
)
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    ClaimCandidate,
    ClaimCoverage,
    CoverageReport,
    EvidencePassage,
    ExperimentConfig,
    ExperimentReport,
    ExperimentStatus,
    GateInputs,
    NeedAggregation,
    NarrativeGapReport,
    PairCandidate,
    PairCoverage,
    PairEvaluation,
    PairFacit,
    PairSelection,
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
        counterparts: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._plan = plan
        self._evidence = list(evidence)
        self._client = client
        self._config = config
        self._narrative = narrative
        self._live_measurement = live_measurement
        self._counterparts = counterparts or {}
        self._embedding_provider: EmbeddingProvider | None = None
        self._started = perf_counter()
        self._groups = group_evidence_for_review(evidence)
        self._passages: list[EvidencePassage] = []
        self._jobs: list[dict[str, object]] = []
        self._items = quality_inputs(evidence)
        self._evaluations: list[PassageEvaluation] = []
        self._claims: tuple[ClaimCandidate, ...] = ()
        self._claims_by_id: dict[str, ClaimCandidate] = {}
        self._passages_by_id: dict[str, EvidencePassage] = {}
        self._claim_coverage: ClaimCoverage | None = None
        self._pair_candidates: dict[str, PairCandidate] = {}
        self._pair_evaluations: list[PairEvaluation] = []
        self._pair_coverage: PairCoverage | None = None
        self._pair_selection: PairSelection | None = None
        self._pair_facit: PairFacit | None = None
        self._coverage_report: CoverageReport | None = None
        self._gap_reviewer: NarrativeGapFn | None = None
        self._gap_review: NarrativeGapReport | None = None
        self._aggregations: tuple[NeedAggregation, ...] = ()
        self._quality: QualityDecision | None = None
        self._route: RouteDecision | None = None
        self._narrative_rounds = 0
        self._draft: ResearchAssessmentDraft | None = None
        self._status: ExperimentStatus = "failed"
        self._failure: str | None = None
        self._jev_calls = 0
        self._llm_calls = 0
        self._source_chars = sum(len(item.excerpt or "") for item in evidence)
        self._judged_chars = 0
        self._coverage = 0.0
        self._missing: tuple[str, ...] = ()
        self._evaluation_errors: tuple[str, ...] = ()
        self.report: ExperimentReport | None = None
        self.handlers: dict[str, Handler] = {
            "sufficiency.prepare": self._prepare,
            "sufficiency.evaluate_one": self._evaluate_one,
            "sufficiency.aggregate": self._aggregate,
            "sufficiency.prepare_pairs": self._prepare_pairs,
            "sufficiency.evaluate_pair": self._evaluate_pair,
            "sufficiency.aggregate_pairs": self._aggregate_pairs,
            "sufficiency.gap_review": self._run_gap_review,
            "sufficiency.route": self._decide_route,
            "sufficiency.narrative": self._run_narrative,
            "sufficiency.emit": self._emit,
        }

    def bind_embedding_provider(self, provider: EmbeddingProvider | None) -> None:
        self._embedding_provider = provider

    def bind_pair_facit(self, facit: PairFacit | None) -> None:
        self._pair_facit = facit

    def bind_gap_reviewer(self, reviewer: NarrativeGapFn | None) -> None:
        self._gap_reviewer = reviewer

    async def run(self, *, run_id: str | None = None) -> RunResult:
        runner = WorkflowRunner(
            compile_sufficiency_workflow(
                self._config.jev_concurrency, self._config.pair_jev_concurrency
            ),
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
        self._claims, self._claim_coverage = extract_claim_candidates(
            self._passages,
            self._evidence_by_id(),
            config=self._config,
        )
        self._claims_by_id = {claim.claim_id: claim for claim in self._claims}
        self._passages_by_id = {
            passage.passage_id: passage for passage in self._passages
        }
        self._jobs = evaluation_jobs(
            self._plan.needs, self._passages, counterparts=self._counterparts
        )
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
            evidence_by_id=self._evidence_by_id(),
            source_types_by_id=present,
        )
        self._aggregations = tuple(rows)
        required = {str(job["job_id"]) for job in self._jobs}
        seen = {row.job_id for row in self._evaluations}
        missing = tuple(sorted(required - seen))
        errors = tuple(row.job_id for row in self._evaluations if row.error)
        coverage = 1.0 if self._source_chars == 0 else self._judged_chars / self._source_chars
        self._coverage = coverage
        self._missing = missing
        self._evaluation_errors = errors
        self._quality = quality_gate(
            self._aggregations,
            GateInputs(
                span_coverage=coverage,
                missing_evaluations=missing,
                evaluation_errors=errors,
                budget_exhausted=self._failure == "budget_exhausted",
                narrative_rounds=self._narrative_rounds,
                claim_coverage_incomplete=bool(
                    self._claim_coverage and not self._claim_coverage.complete
                ),
            ),
            self._config,
        )
        return {
            "need_count": len(self._aggregations),
            "allows_sufficient": self._quality.allows_sufficient,
        }

    async def _prepare_pairs(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self._config.pair_judgement or not self._claims:
            self._pair_coverage = pair_coverage(())
            return {"jobs": []}
        selection = await select_ordered_pairs(
            self._claims,
            self._plan.needs,
            self._claims_by_id,
            strategy=self._config.pair_strategy,
            ordering=self._config.pair_ordering,
            config=self._config,
            embedding_provider=self._embedding_provider,
        )
        self._pair_selection = selection
        self._pair_candidates = {
            pair.pair_id: pair for pair in selection.selected
        }
        return {
            "jobs": [
                {"pair_id": pair.pair_id, "need_id": pair.need_id}
                for pair in selection.selected
            ],
            "candidate_pairs": len(selection.candidates),
            "selected_pairs": len(selection.selected),
            "omitted_by_budget": selection.omitted_by_budget,
        }

    async def _evaluate_pair(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        pair = self._pair_candidates[str(payload["item"]["pair_id"])]
        row = await evaluate_pair(
            pair,
            claims=self._claims_by_id,
            passages=self._passages_by_id,
            evidence_by_id=self._evidence_by_id(),
            client=self._client,
            config=self._config,
        )
        if row.error not in {"pair_state_budget", "pair_call_budget"}:
            self._jev_calls += 1
        self._pair_evaluations.append(row)
        return {"pair_id": row.pair_id, "status": row.status, "verdict": row.verdict}

    async def _aggregate_pairs(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self._config.pair_judgement:
            self._pair_selection = None
            self._pair_evaluations = []
        coverage = pair_coverage(self._pair_evaluations)
        self._pair_coverage = coverage
        self._aggregations = tuple(
            merge_pair_conflicts(
                self._aggregations,
                self._pair_evaluations,
                claims=self._claims_by_id,
                evidence_by_id=self._evidence_by_id(),
            )
        )
        self._coverage_report = build_coverage_report(
            evidence=self._evidence,
            source_chars=self._source_chars,
            judged_chars=self._judged_chars,
            claim_coverage=self._claim_coverage,
            pair_selection=self._pair_selection,
            pair_evaluations=self._pair_evaluations,
            pair_facit=self._pair_facit,
        )
        self._quality = quality_gate(
            self._aggregations,
            GateInputs(
                span_coverage=self._coverage,
                missing_evaluations=self._missing,
                evaluation_errors=self._evaluation_errors,
                budget_exhausted=self._failure == "budget_exhausted",
                narrative_rounds=self._narrative_rounds,
                claim_coverage_incomplete=bool(
                    self._claim_coverage and not self._claim_coverage.complete
                ),
                pair_coverage_incomplete=not coverage.complete,
                coverage_incomplete=not self._coverage_report.gate_complete,
            ),
            self._config,
        )
        return {
            "judged_pairs": coverage.judged,
            "unevaluated_pairs": coverage.unevaluated,
            "allows_sufficient": self._quality.allows_sufficient,
        }

    async def _run_gap_review(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self._config.gap_review_enabled or self._gap_reviewer is None:
            return {"ran": False}
        payload = build_gap_payload(
            self._plan,
            self._aggregations,
            claims=self._claims,
            selection=self._pair_selection,
            coverage=self._coverage_report,
            max_chars=self._config.max_gap_input_chars,
        )
        self._gap_review = await run_gap_review(
            payload, completer=self._gap_reviewer, config=self._config
        )
        self._llm_calls += 1
        return {
            "ran": True,
            "needs_more_evidence": self._gap_review.needs_more_evidence,
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
                if self._config.route_authority:
                    self._status, reason = status_from_route(
                        self._route, self._quality, self._aggregations
                    )
                    if reason:
                        self._failure = self._failure or reason
                else:
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

    def _evidence_by_id(self) -> dict[str, AssessableEvidence]:
        return {item.evidence_id: item for item in self._evidence}

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
            claims=self._claims,
            claim_coverage=self._claim_coverage,
            pairs=tuple(self._pair_evaluations),
            pair_coverage=self._pair_coverage,
            coverage_report=self._coverage_report,
            gap_review=self._gap_review,
        )
