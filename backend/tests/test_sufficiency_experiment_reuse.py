"""Reuse-path tests: SWE runner, Jev NOUL, quality independence, assessment."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.config import settings
from app.services.research.assessment import (
    group_evidence_for_review,
    sanitize_assessment_draft,
)
from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
from app.services.research.fast_controller import (
    ASSESSMENT_QUESTIONS,
    classify_research_decision,
)
from app.services.research.quality import independence_key
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.benchmark import (
    live_measurement_status,
    measure_live_models,
)
from app.services.research.sufficiency_experiment.golden import (
    duplicate_sources,
    later_wave_contradiction,
    missing_source_type,
    multi_obligation,
    no_support,
    short_sufficient,
    unknown_requirements,
)
from app.services.research.sufficiency_experiment.jev_eval import (
    evaluate_job,
    quality_input_from_evidence,
)
from app.services.research.sufficiency_experiment.route import map_jev_outcome, route_state
from app.services.research.sufficiency_experiment.scripted import ScriptedSufficiencyJev
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    QualityDecision,
)
from app.swe.runtime import WorkflowRunner

pytestmark = [pytest.mark.asyncio, pytest.mark.swe_runtime]


@pytest.fixture
def client() -> ScriptedSufficiencyJev:
    return ScriptedSufficiencyJev()


async def test_sufficiency_runs_through_swe_native(client: ScriptedSufficiencyJev) -> None:
    pytest.importorskip("swe_native")
    case = short_sufficient()
    report = await run_experiment(case.plan, case.evidence, client=client)
    assert report.swe_run_id
    assert "NodeCompleted" in report.swe_events
    assert "DecisionTaken" in report.swe_events
    assert "BranchSpawned" in report.swe_events
    assert report.status == "sufficient"
    assert report.draft.result == "sufficient"


async def test_run_experiment_uses_workflow_runner(
    client: ScriptedSufficiencyJev, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("swe_native")
    called: list[str] = []
    original = WorkflowRunner.run

    async def wrapped(self, input_data=None, *, run_id=None):
        called.append(self.compiled.name)
        return await original(self, input_data, run_id=run_id)

    monkeypatch.setattr(WorkflowRunner, "run", wrapped)
    await run_experiment(short_sufficient().plan, short_sufficient().evidence, client=client)
    assert called == ["evidence_sufficiency"]


async def test_passage_eval_uses_evidence_screen_questions(
    client: ScriptedSufficiencyJev,
) -> None:
    seen: list[set[str]] = []
    original = client.ask

    async def wrapped(*, state, questions, model, timeout_seconds):
        seen.append(set(questions))
        return await original(
            state=state, questions=questions, model=model, timeout_seconds=timeout_seconds
        )

    client.ask = wrapped  # type: ignore[method-assign]
    case = short_sufficient()
    passage = segment_evidence(case.evidence, max_chars=1_500)[0]
    job = {
        "job_id": "research_1:p0",
        "need_id": "research_1",
        "question": case.plan.needs[0].question,
        "passage_id": passage.passage_id,
        "evidence_id": passage.evidence_id,
        "text": passage.text,
        "content_hash": passage.content_hash,
        "start": passage.start,
        "end": passage.end,
    }
    await evaluate_job(job, client, ExperimentConfig())
    assert seen
    assert set(EVIDENCE_SCREEN_QUESTIONS) <= seen[0]


async def test_route_uses_classify_research_decision() -> None:
    outcome = classify_research_decision(
        answerable_now=0.95,
        material_gap=0.05,
        contradiction=0.05,
        follow_up_change=0.05,
        additional_source=0.05,
        confidence=0.95,
        sufficient_threshold=0.9,
        incomplete_threshold=0.85,
        confidence_threshold=0.8,
    )
    quality = QualityDecision(
        allows_sufficient=True,
        escalate_permitted=False,
        applicable_subworkflows=(),
        reasons=(),
        span_coverage=1.0,
        semantic_complete=True,
        omitted_evidence_ids=(),
        missing_evaluations=(),
        budget_exhausted=False,
    )
    assert map_jev_outcome(outcome, quality, ()) == "FINISH"
    state = route_state((), quality)
    assert "obligations_verified" in state
    assert set(ASSESSMENT_QUESTIONS) >= {
        "answerable_now",
        "material_gap",
        "contradiction",
        "follow_up_change",
        "additional_source",
    }


async def test_duplicate_sources_are_one_independence_key(client: ScriptedSufficiencyJev) -> None:
    case = duplicate_sources()
    keys = {independence_key(quality_input_from_evidence(item)) for item in case.evidence}
    assert keys == {"source-shared"}
    report = await run_experiment(case.plan, case.evidence, client=client)
    assert report.draft.result == "insufficient"
    assert report.status == "insufficient"
    support = report.aggregations[0].obligation_states
    factual = next(state for state in support if state.kind == "factual_support")
    assert factual.independent_support == 1


async def test_quality_independence_blocks_false_corroboration(
    client: ScriptedSufficiencyJev,
) -> None:
    case = duplicate_sources()
    report = await run_experiment(case.plan, case.evidence, client=client)
    assert "obligations_unverified" in report.quality.reasons
    assert report.quality.allows_sufficient is False


async def test_group_then_segment_keeps_need_lineage() -> None:
    case = duplicate_sources()
    groups = group_evidence_for_review(case.evidence)
    assert groups
    assert all(group.research_need_ids == ("research_1",) for group in groups)
    passages = segment_evidence(case.evidence, max_chars=1_500)
    assert {item.evidence_id for item in passages} == {item.evidence_id for item in case.evidence}


async def test_unknown_source_types_are_uncertain(client: ScriptedSufficiencyJev) -> None:
    case = unknown_requirements()
    report = await run_experiment(case.plan, case.evidence, client=client)
    assert report.status == "uncertain"
    assert report.draft.result == "insufficient"
    assert report.aggregations[0].unknown_requirements is True


async def test_multi_obligation_and_missing_source(client: ScriptedSufficiencyJev) -> None:
    for case in (multi_obligation(), missing_source_type(), no_support()):
        report = await run_experiment(case.plan, case.evidence, client=client)
        assert report.draft.result == "insufficient", case.case_id
        assert report.status == "insufficient", case.case_id
        assert report.quality.allows_sufficient is False


async def test_later_wave_contradiction_is_preserved(client: ScriptedSufficiencyJev) -> None:
    case = later_wave_contradiction()
    report = await run_experiment(case.plan, case.evidence, client=client)
    assert report.status == "uncertain"
    assert report.aggregations[0].unresolved_conflicts
    assert report.draft.result == "insufficient"


async def test_sanitize_blocks_invented_ids(client: ScriptedSufficiencyJev) -> None:
    case = short_sufficient()
    report = await run_experiment(case.plan, case.evidence, client=client)
    forged = replace(
        report.draft,
        need_assessments=[
            replace(
                report.draft.need_assessments[0],
                supporting_evidence_ids=["invented-id"],
            )
        ],
    )
    cleaned = sanitize_assessment_draft(forged, plan=case.plan, evidence=case.evidence)
    assert cleaned.result == "insufficient"
    assert "invented-id" not in cleaned.need_assessments[0].supporting_evidence_ids


async def test_live_measurement_reports_unavailable_without_keys(monkeypatch) -> None:
    monkeypatch.setattr(settings, "typesafe_api_key", "")
    report = await measure_live_models((short_sufficient(),))
    assert report.measurement == "unavailable"
    assert report.cases == ()
    assert "invented" in report.note or "missing" in report.note


def test_live_measurement_never_substitutes_scripted_scores(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cerebras_api_key", "")
    assert live_measurement_status() == "unavailable"


class _RecordingJev:
    def __init__(self) -> None:
        self.questions: list[set[str]] = []

    async def ask(self, *, state, questions, model, timeout_seconds):
        self.questions.append(set(questions))
        inner = ScriptedSufficiencyJev()
        return await inner.ask(
            state=state, questions=questions, model=model, timeout_seconds=timeout_seconds
        )


async def test_experiment_asks_assessment_questions() -> None:
    pytest.importorskip("swe_native")
    client = _RecordingJev()
    await run_experiment(short_sufficient().plan, short_sufficient().evidence, client=client)
    assert any(set(ASSESSMENT_QUESTIONS) <= asked for asked in client.questions)
    assert any(set(EVIDENCE_SCREEN_QUESTIONS) <= asked for asked in client.questions)
