"""Workflow-first policy: allowlisted tools, gates, production unchanged."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.llm.research_assessment import LlmResearchAssessor
from app.services.research.sufficiency_experiment.quality import quality_gate
from app.services.research.sufficiency_experiment.tools import (
    ALLOWED_WORKFLOWS,
    UnknownWorkflowToolError,
    invoke_workflow,
)
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    GateInputs,
    NeedAggregation,
    ObligationState,
)


def test_production_assessor_still_uses_pr420_budget() -> None:
    source = inspect.getsource(LlmResearchAssessor.assess)
    assert "encode_assessment_input" in source
    assert "ASSESSMENT_MAX_INPUT_CHARS" in source
    assert "sufficiency_experiment" not in source


def test_production_modules_do_not_import_the_experiment() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    forbidden = (
        root / "llm" / "research_assessment.py",
        root / "services" / "research" / "execution.py",
        root / "services" / "research_worker.py",
        root / "services" / "research" / "loop_control.py",
    )
    for path in forbidden:
        assert "sufficiency_experiment" not in path.read_text(encoding="utf-8")


def test_experiment_does_not_import_loop_control() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "services" / "research" / "sufficiency_experiment"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "loop_control" not in text
        assert "loop_decision" not in text


def test_agent_tools_are_typed_workflows_only() -> None:
    assert "search" not in ALLOWED_WORKFLOWS
    assert "database" not in ALLOWED_WORKFLOWS
    assert "resolve_conflict" in ALLOWED_WORKFLOWS


@pytest.mark.asyncio
async def test_unknown_and_forbidden_tools_fail_loudly() -> None:
    config = ExperimentConfig()

    async def segment(payload: dict) -> dict:
        return payload

    registry = {"segment_passages": segment}
    with pytest.raises(UnknownWorkflowToolError, match="search"):
        await invoke_workflow("search", {}, registry, depth=0, config=config)
    with pytest.raises(UnknownWorkflowToolError, match="database"):
        await invoke_workflow("database", {}, registry, depth=0, config=config)
    result, event = await invoke_workflow(
        "segment_passages",
        {"ok": True},
        registry,
        depth=0,
        config=config,
    )
    assert result == {"ok": True}
    assert event.workflow == "segment_passages"


def _aggregation(*, sufficient: bool = False, unknown: bool = False, conflicts: tuple[str, ...] = ()) -> NeedAggregation:
    return NeedAggregation(
        research_need_id="research_1",
        status="uncertain" if conflicts or unknown else "insufficient",
        sufficient=sufficient,
        obligation_states=(
            ObligationState(
                obligation_id="research_1:factual_support",
                kind="factual_support",
                verified=sufficient,
                independent_support=1 if sufficient else 0,
                contradicting_passage_ids=("p1",) if conflicts else (),
                addressed=False,
            ),
        ),
        supporting_evidence_ids=(),
        contradictions=("p1",) if conflicts else (),
        unresolved_conflicts=conflicts,
        missing_or_weak="gap",
        unknown_requirements=unknown,
    )


def test_quality_gate_blocks_sufficient_on_incomplete_coverage() -> None:
    config = ExperimentConfig()
    blocked = quality_gate(
        [_aggregation()],
        GateInputs(span_coverage=0.5, omitted_evidence_ids=("evidence-9",)),
        config,
    )
    assert blocked.allows_sufficient is False
    assert blocked.escalate_permitted is False
    assert "span_coverage_incomplete" in blocked.reasons
    assert "evidence_omitted" in blocked.reasons


def test_quality_gate_prefers_resolve_conflict_before_narrative() -> None:
    config = ExperimentConfig()
    decision = quality_gate(
        [_aggregation(conflicts=("research_1:factual_support",))],
        GateInputs(span_coverage=1.0),
        config,
    )
    assert decision.applicable_subworkflows == ("resolve_conflict",)
    assert decision.escalate_permitted is False
