import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.services.research.assessment import ResearchAssessmentDraft
from app.services.research.followup import RuntimeResearchNeed
from tests.research_reuse.coverage import (
    Criterion,
    CriterionResult,
    CoverageEvaluator,
    CoverageResult,
    Overlap,
    QuestionReference,
    build_evaluator,
    validate_coverage,
)
from tests.research_reuse.helpers import context

pytestmark = pytest.mark.research_reuse


def question():
    return RuntimeResearchNeed(
        research_need_id="q1",
        question="Hur tillämpas 36 § i konsumentavtal?",
        why_needed="Konsumentavtal och arbetsavtal saknas",
        source_types=["swedish_case_law"],
    )


def criteria():
    return [
        Criterion(id="consumer", requirement="Konsumentavtal", source_types=["swedish_case_law"]),
        Criterion(id="employment", requirement="Arbetsavtal", source_types=["swedish_case_law"]),
    ]


def result():
    return CoverageResult(
        criteria=[
            CriterionResult(
                criterion_id="consumer",
                status="covered",
                rationale="Requested explicitly",
                references=[QuestionReference(research_need_id="q1", quote="konsumentavtal")],
            ),
            CriterionResult(
                criterion_id="employment", status="missing", rationale="Only in why_needed"
            ),
        ]
    )


async def test_missing_contract_type_fails_even_with_fewer_questions():
    completer = AsyncMock(return_value=result())
    evaluator = CoverageEvaluator(
        {
            "research.followup.coverage.system": "Mock judge",
            "research.followup.coverage.user": "{payload_json}",
        },
        completer=completer,
    )
    judged = await evaluator.evaluate(
        "36 §",
        ResearchAssessmentDraft(result="insufficient", rationale="Missing types"),
        [question()],
        criteria(),
    )
    assert not judged.passed
    assert judged.criteria[1].status == "missing"
    assert "Arbetsavtal" in completer.call_args.args[0][1]["content"]


@pytest.mark.parametrize("status", ["partial", "missing"])
def test_partial_or_missing_criterion_cannot_pass(status):
    judged = result()
    judged.criteria[1].status = status
    if status == "partial":
        judged.criteria[1].references = judged.criteria[0].references
    assert not judged.passed


@pytest.mark.parametrize(
    "mutation", ["omit", "duplicate", "unknown", "false_quote", "wrong_sources"]
)
def test_invalid_judge_output_fails_loudly(mutation):
    judged = result()
    rubric = criteria()
    if mutation == "omit":
        judged.criteria.pop()
    elif mutation == "duplicate":
        judged.criteria.append(judged.criteria[0])
    elif mutation == "unknown":
        judged.criteria[0].references[0].research_need_id = "invented"
    elif mutation == "false_quote":
        judged.criteria[0].references[0].quote = "arbetsavtal"
    else:
        rubric[0].source_types = ["swedish_preparatory_works"]
    with pytest.raises(ValueError):
        validate_coverage(judged, [question()], rubric)


def test_complete_coverage_passes_but_redundancy_and_broadness_fail():
    second = replace(
        question(), research_need_id="q2", question="Hur tillämpas 36 § i arbetsavtal?"
    )
    judged = result()
    judged.criteria[1] = CriterionResult(
        criterion_id="employment",
        status="covered",
        rationale="Explicit",
        references=[QuestionReference(research_need_id="q2", quote="arbetsavtal")],
    )
    validate_coverage(judged, [question(), second], criteria())
    assert judged.passed
    judged.redundant_pairs = [Overlap(question_ids=["q1", "q2"], rationale="Mock semantic overlap")]
    assert not judged.passed
    judged.redundant_pairs = []
    judged.overbroad_question_ids = ["q1"]
    assert not judged.passed


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_judge_releases_one_connection_pool_before_call(reuse_db, monkeypatch, outcome):
    async def load(session, **kwargs):
        await session.execute(text("SELECT 1"))
        return {
            "research.followup.coverage.system": "Mock",
            "research.followup.coverage.user": "{payload_json}",
        }

    monkeypatch.setattr("tests.research_reuse.coverage.require_active_prompts", load)
    entered, release = asyncio.Event(), asyncio.Event()

    async def complete(*args, **kwargs):
        entered.set()
        await release.wait()
        if outcome == "error":
            raise RuntimeError("Judge unavailable")
        return result()

    evaluator = await build_evaluator(reuse_db, context(), completer=complete)
    task = asyncio.create_task(
        evaluator.evaluate(
            "36 §",
            ResearchAssessmentDraft(result="insufficient", rationale="Missing"),
            [question()],
            criteria(),
        )
    )
    await asyncio.wait_for(entered.wait(), 1)
    async with reuse_db() as session:
        assert await session.scalar(text("SELECT 1")) == 1
    if outcome == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        release.set()
        if outcome == "error":
            with pytest.raises(RuntimeError, match="unavailable"):
                await task
        else:
            assert not (await task).passed


async def test_live_lab_keeps_every_iteration_and_binds_rubric(reuse_db, tmp_path, monkeypatch):
    import json
    from dataclasses import asdict
    from types import SimpleNamespace

    from tests.research_reuse import coverage_live
    from tests.research_reuse.helpers import evidence, need
    from tests.research_reuse.snapshots import ASSESSMENT, EVIDENCE, digest, save

    current, scope = need(), context()
    assessment = ResearchAssessmentDraft(result="insufficient", rationale="Missing types")
    identity = {"attempt_id": "fixture", "need": asdict(current), "context": asdict(scope)}
    first = EVIDENCE.dump_python([evidence()], mode="json")
    second = ASSESSMENT.dump_python(assessment, mode="json")
    save(tmp_path / "step_1.json", target=identity, stage=1, payload=first)
    save(tmp_path / "step_2.json", target=identity, stage=2, payload=second, parent=digest(first))
    rubric = tmp_path / "rubric.json"
    rubric.write_text(
        json.dumps(
            {
                "question": current.question,
                "assessment_digest": digest(second),
                "criteria": [row.model_dump() for row in criteria()],
            }
        )
    )
    monkeypatch.setattr(coverage_live, "create_async_engine", lambda *a, **kw: reuse_db.kw["bind"])
    monkeypatch.setattr(coverage_live, "workload", AsyncMock(return_value=(current, scope, {})))
    evaluator = AsyncMock()
    evaluator.evaluate.return_value = result()
    monkeypatch.setattr(coverage_live, "build_evaluator", AsyncMock(return_value=evaluator))
    planner = AsyncMock(return_value=[question()])
    monkeypatch.setattr(coverage_live, "gaps", planner)
    args = SimpleNamespace(
        workspace=str(tmp_path),
        output="report.json",
        rubric=str(rubric),
        attempt_id="fixture",
        need_id=None,
        repeat=2,
    )
    report = await coverage_live.run(args)
    assert len(report["runs"]) == 2
    assert all(
        not row["passed"] and row["questions"][0]["question"] == question().question
        for row in report["runs"]
    )
    assert json.loads((tmp_path / "report.json").read_text()) == report
    assert planner.await_count == evaluator.evaluate.await_count == 2
    with pytest.raises(FileExistsError):
        await coverage_live.run(args)
    args.output = "other-report.json"
    data = json.loads(rubric.read_text())
    data["assessment_digest"] = "changed"
    rubric.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Rubric must match"):
        await coverage_live.run(args)
    assert planner.await_count == 2
