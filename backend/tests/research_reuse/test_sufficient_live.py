"""CI checks the strict live probe with real SQL and mocked external judgments."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.services.research.assessment import ResearchAssessmentDraft, ResearchNeedAssessment
from tests.research_reuse import probes, sufficient_live
from tests.research_reuse.helpers import CHILD, context, need, reviewed_answer
from tests.research_reuse.test_01_saved_answer import saved_questions
from tests.test_research_graph_v2_reuse import Embeddings

pytestmark = pytest.mark.research_reuse


def test_live_probe_imports_in_a_fresh_process_without_pytest_bootstrap():
    import subprocess
    import sys
    from pathlib import Path

    code = """
import socket
def forbidden(*args, **kwargs):
    raise RuntimeError("CI must not connect to external services")
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
import tests.research_reuse.sufficient_live
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("judgment", ["sufficient", "insufficient", "invented-citation"])
async def test_live_contract_requires_a_valid_new_judgment_on_a_saved_answer(
    reuse_db, monkeypatch, judgment,
):
    canonical = (await saved_questions(reuse_db))[CHILD]
    real_assess = probes.assess

    async def assessed(plan, items):
        async with reuse_db() as other:
            assert await other.scalar(text("SELECT 1")) == 1
        if judgment == "sufficient":
            return await reviewed_answer(plan, items)
        return ResearchAssessmentDraft(
            result="insufficient" if judgment == "insufficient" else "sufficient",
            rationale="New judgment",
            need_assessments=[ResearchNeedAssessment(
                research_need_id="child", sufficient=judgment != "insufficient",
                supporting_evidence_ids=["invented"],
            )],
        )

    adapter = SimpleNamespace(assess=AsyncMock(side_effect=assessed))

    async def builder(session, **_kwargs):
        await session.execute(text("SELECT 1"))
        return adapter

    async def mocked_model(factory, question, items, scope, *, timings):
        return await real_assess(
            factory, question, items, scope, builder=builder, timings=timings,
        )

    monkeypatch.setattr(probes, "assess", mocked_model)
    forbidden = AsyncMock(side_effect=AssertionError("Unexpected gap planner"))
    monkeypatch.setattr(probes, "build_llm_follow_up_planner", forbidden)
    result = await sufficient_live.measure(
        reuse_db, need(question_id=canonical), context(), Embeddings(),
    )
    assert result["checks"]["fresh_saved_answer"]
    assert result["contract_passed"] is (judgment == "sufficient")
    assert result["source_retrieval"] == "not_run"
    assert result["answer_fact_ids"]
    adapter.assess.assert_awaited_once()
    forbidden.assert_not_awaited()


async def test_live_contract_fails_without_saved_episodes(graph_basis, monkeypatch):
    forbidden = AsyncMock(side_effect=AssertionError("No saved answer to assess"))
    monkeypatch.setattr(probes, "assess", forbidden)
    result = await sufficient_live.measure(graph_basis, need(), context(), Embeddings())
    assert not result["contract_passed"]
    assert not result["checks"]["fresh_saved_answer"]
    forbidden.assert_not_awaited()


async def test_model_failure_propagates_and_releases_pool(reuse_db, monkeypatch):
    canonical = (await saved_questions(reuse_db))[CHILD]
    monkeypatch.setattr(probes, "assess", AsyncMock(side_effect=RuntimeError("Model unavailable")))
    with pytest.raises(RuntimeError, match="Model unavailable"):
        await sufficient_live.measure(reuse_db, need(question_id=canonical), context(), Embeddings())
    async with reuse_db() as session:
        assert await session.scalar(text("SELECT 1")) == 1


async def test_promoted_subquestion_keeps_identity_and_uses_main_question_input(monkeypatch):
    from app.services.research.startup import MAIN_NEED_ID

    selected = need(question_id="existing-canonical")
    original = AsyncMock(return_value=(selected, context(), {"model": "configured"}))
    monkeypatch.setattr(sufficient_live, "workload", original)
    main, scope, metadata = await sufficient_live.selected_workload(
        object(), "prior-attempt", "child", as_main=True,
    )
    assert main.id == MAIN_NEED_ID
    assert main.question == selected.question
    assert main.knowledge_question_id == selected.knowledge_question_id
    assert set(main.source_types).issuperset(selected.source_types)
    assert scope == context() and metadata == {"model": "configured"}
