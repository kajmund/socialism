"""Differential tests: phase-2 research loop vs the SWE bridge.

Both paths get the same attempt, plan, router, assessor and planner. The only
difference is which function `execute_attempt_research` calls for the wave loop
(`app.services.research.execution._run_research_loop` is patched), so the
persisted domain state must match exactly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

pytest.importorskip("swe_native")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base
from app.services.execution import (
    get_attempt,
    get_evidence_set,
    list_evidence_items,
    list_need_executions,
    list_research_assessments,
    list_runtime_needs,
)
from app.services.research import swe_bridge
from app.services.research.execution import execute_attempt_research
from app.services.research.models import ResearchPlan
from app.swe.features import WorkflowHostContext
from app.services.overgraph.workflows import WorkflowRunStore
from tests.test_research_assessment import RecordingAssessor, _fixed_draft
from tests.test_research_execution import RecordingSource, _created_attempt, _need, _router
from tests.test_research_loop import ScriptedPlanner, SequenceAssessor, _follow_up

pytestmark = [
    pytest.mark.swe_runtime,
    pytest.mark.usefixtures("graph_retrieval_embeddings"),
]

Scenario = Callable[[], tuple[ResearchPlan, Any, Any, Any]]
LoopImpl = Callable[..., Awaitable[None]]


@dataclass(frozen=True)
class _Snapshot:
    status: str
    stop_reason: str | None
    wave: int
    evidence_status: str
    evidence: tuple[tuple[object, ...], ...]
    executions: tuple[tuple[str, str], ...]
    assessments: tuple[tuple[int, str], ...]
    runtime_needs: tuple[tuple[str, str, int], ...]


def _sufficient_scenario() -> tuple[ResearchPlan, Any, Any, Any]:
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    router, _ = _router(RecordingSource("case_knowledge"))
    return plan, router, RecordingAssessor(), ScriptedPlanner([])


def _follow_up_scenario() -> tuple[ResearchPlan, Any, Any, Any]:
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    router, _ = _router(RecordingSource("case_knowledge"))
    assessor = SequenceAssessor(
        [
            _fixed_draft(
                result="insufficient",
                need_id="research_1",
                evidence_ids=[],
                further="Behöver taxa.",
            ),
            _fixed_draft(result="sufficient", need_id="research_1", evidence_ids=[]),
        ]
    )
    planner = ScriptedPlanner([[_follow_up("Vad är kommunens taxa?")]])
    return plan, router, assessor, planner


async def _run(
    tmp_path: Path,
    name: str,
    scenario: Scenario,
    *,
    loop_impl: LoopImpl | None = None,
) -> _Snapshot:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/{name}.sqlite",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA journal_mode=WAL"))
    try:
        async with factory() as session:
            _customer, _run_row, attempt = await _created_attempt(session, slug=f"diff-{name}")
            plan, router, assessor, planner = scenario()
            kwargs = {
                "attempt_id": attempt.id,
                "research_plan": plan,
                "router": router,
                "assessor": assessor,
                "planner": planner,
            }
            if loop_impl is None:
                result = await execute_attempt_research(session, **kwargs)
            else:
                with mock.patch(
                    "app.services.research.execution._run_research_loop", loop_impl,
                ):
                    result = await execute_attempt_research(session, **kwargs)
            return await _snapshot(session, attempt.id, result)
    finally:
        await engine.dispose()


async def _snapshot(session: AsyncSession, attempt_id: str, result: Any) -> _Snapshot:
    attempt = await get_attempt(session, attempt_id)
    evidence_set = (
        await get_evidence_set(session, result.evidence_set_id)
        if result.evidence_set_id is not None
        else None
    )
    items = (
        await list_evidence_items(session, result.evidence_set_id)
        if result.evidence_set_id is not None
        else []
    )
    executions = await list_need_executions(session, attempt_id)
    assessments = await list_research_assessments(session, attempt_id)
    runtime_needs = await list_runtime_needs(session, attempt_id)
    return _Snapshot(
        status=result.status,
        stop_reason=attempt.research_stop_reason,
        wave=attempt.research_wave,
        evidence_status=evidence_set.status if evidence_set is not None else "none",
        evidence=tuple(
            sorted(
                (item.research_need_id or "", item.source_type, item.status, item.excerpt or "")
                for item in items
            )
        ),
        executions=tuple(
            sorted((row.research_need_id, row.status) for row in executions)
        ),
        assessments=tuple(
            sorted((row.assessment_pass, row.result) for row in assessments)
        ),
        runtime_needs=tuple(
            sorted((row.question, row.origin, row.wave_number) for row in runtime_needs)
        ),
    )


async def test_initial_wave_parity(tmp_path: Path) -> None:
    baseline = await _run(tmp_path, "base", _sufficient_scenario)
    variant_a = await _run(
        tmp_path, "a", _sufficient_scenario,
        loop_impl=swe_bridge.run_research_loop_via_swe,
    )
    variant_b = await _run(
        tmp_path, "b", _sufficient_scenario,
        loop_impl=swe_bridge.run_research_loop_via_swe_parallel,
    )
    assert baseline.status == "ready"
    assert baseline.stop_reason == "sufficient"
    assert variant_a == baseline
    assert variant_b == baseline


async def test_follow_up_wave_parity(tmp_path: Path) -> None:
    baseline = await _run(tmp_path, "base", _follow_up_scenario)
    variant = await _run(
        tmp_path, "swe", _follow_up_scenario,
        loop_impl=swe_bridge.run_research_loop_via_swe,
    )
    assert baseline.status == "ready"
    assert baseline.wave == 1
    assert variant == baseline


async def test_parallel_variant_follow_up_parity(tmp_path: Path) -> None:
    baseline = await _run(tmp_path, "base", _follow_up_scenario)
    variant = await _run(
        tmp_path, "swe-parallel", _follow_up_scenario,
        loop_impl=swe_bridge.run_research_loop_via_swe_parallel,
    )
    assert variant == baseline


async def test_swe_run_is_persisted_in_the_overgraph_run_store(tmp_path: Path) -> None:
    store = WorkflowRunStore.open(
        tmp_path / "overgraph",
        WorkflowHostContext(customer_id="1", feature_id="research"),
    )
    try:
        async def stored_loop(**kwargs: object) -> None:
            loop, plan = swe_bridge.build_loop(kwargs, concurrency=4, run_store=store)
            result = await loop.run(snapshot_plan=plan, run_id="run-research-parity")
            assert result.status == "completed"

        snapshot = await _run(
            tmp_path, "store", _sufficient_scenario, loop_impl=stored_loop,
        )
        stored = await store.load_run("run-research-parity")
        events = await store.events("run-research-parity")
        replay = await store.replay_results("run-research-parity")
    finally:
        store.close()

    assert snapshot.status == "ready"
    assert stored is not None
    assert stored.status == "completed"
    assert stored.finished_at_ms is not None
    assert stored.definition_sha256 == swe_bridge._workflow(4).sha256
    assert events
    assert replay


def test_variants_differ_only_in_fanout_concurrency() -> None:
    narrow = swe_bridge._workflow(4)
    wide = swe_bridge._workflow(8)
    assert narrow.sha256 != wide.sha256
    assert set(narrow.document["nodes"]) == set(wide.document["nodes"])
    assert narrow.document["nodes"]["needs"]["concurrency"] == 4
    assert wide.document["nodes"]["needs"]["concurrency"] == 8
    assert narrow.document["nodes"]["execute_need"] == wide.document["nodes"]["execute_need"]
