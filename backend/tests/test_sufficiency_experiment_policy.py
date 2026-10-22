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
    NeedAggregation,
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
    )
    for path in forbidden:
        assert "sufficiency_experiment" not in path.read_text(encoding="utf-8")


def test_agent_tools_are_typed_workflows_only() -> None:
    assert "search" not in ALLOWED_WORKFLOWS
    assert "database" not in ALLOWED_WORKFLOWS


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


def test_narrative_requires_jev_and_quality_gates() -> None:
    config = ExperimentConfig()
    undecided = NeedAggregation(
        research_need_id="research_1",
        sufficient=False,
        supporting_evidence_ids=(),
        contradictions=(),
        undecided_passage_ids=("p0",),
        missing_or_weak="undecided",
        needs_narrative=True,
    )
    blocked = quality_gate(
        [undecided],
        coverage=0.5,
        omitted_evidence_ids=("evidence-9",),
        recursion_depth=0,
        config=config,
        jev_requires_narrative=True,
    )
    assert blocked.escalate is False
    assert "coverage_incomplete" in blocked.reasons
    assert "evidence_omitted" in blocked.reasons
    allowed = quality_gate(
        [undecided],
        coverage=1.0,
        omitted_evidence_ids=(),
        recursion_depth=0,
        config=config,
        jev_requires_narrative=True,
    )
    assert allowed.escalate is True
