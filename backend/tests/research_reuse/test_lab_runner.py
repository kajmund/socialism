import asyncio
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.services.research.assessment import ResearchAssessmentDraft
from app.services.research.followup import FollowUpNeedDraft
from tests.research_reuse import live, probes
from tests.research_reuse.helpers import context, evidence, need
from tests.research_reuse.snapshots import (
    ASSESSMENT,
    EVIDENCE,
    TimedStep,
    digest,
    read,
    save,
    summary,
)

pytestmark = pytest.mark.research_reuse


def test_ci_refuses_unmocked_network_connections():
    import socket

    with socket.socket() as connection:
        with pytest.raises(RuntimeError, match="must mock every network boundary"):
            connection.connect(("127.0.0.1", 9))


async def test_real_source_probe_releases_pool_and_closes_client(reuse_db, monkeypatch):
    client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(live, "OfficialLagenNuMcpClient", lambda: client)
    constructed = []

    def source_factory(**kwargs):
        constructed.append(kwargs)

        async def research(_need, _context):
            async with reuse_db() as other:
                assert await asyncio.wait_for(other.scalar(text("SELECT 1")), timeout=1) == 1
            return [evidence()]

        return SimpleNamespace(research=research)

    monkeypatch.setattr(live, "LagenNuResearchSource", source_factory)
    from app.services.research.followup import runtime_needs_from_plan
    from app.services.research.models import ResearchPlan

    row = runtime_needs_from_plan(ResearchPlan(needs=[need()]))[0]
    result = await live.fetch_gap(reuse_db, row, context())
    assert result[0].source_id == "law"
    assert "session" not in constructed[0], (
        "Source probe must not hold a DB session during retrieval"
    )
    client.aclose.assert_awaited_once()


def test_replay_preserves_evidence_and_rejects_other_scope_and_changed_parent(tmp_path):
    target = {"customer_id": 1, "question": need().question}
    path = tmp_path / "step_1.json"
    original = evidence()
    payload = EVIDENCE.dump_python([original], mode="json")
    save(path, target=target, stage=1, payload=payload)
    row = read(path, target=target, stage=1)
    assert EVIDENCE.validate_python(row["payload"]) == [original]
    with pytest.raises(ValueError, match="does not match"):
        read(path, target={**target, "customer_id": 2}, stage=1)
    second = tmp_path / "step_2.json"
    save(second, target=target, stage=2, payload={}, parent=digest(payload))
    with pytest.raises(ValueError, match="previous stage"):
        read(second, target=target, stage=2, parent=digest([]))


def test_missing_replay_file_fails_instead_of_running_previous_steps(tmp_path):
    with pytest.raises(FileNotFoundError):
        read(tmp_path / "missing.json", target={}, stage=1)


def test_failed_step_records_duration_and_propagates_error():
    measurements = []
    with pytest.raises(RuntimeError, match="unavailable"):
        with TimedStep(2, measurements):
            raise RuntimeError("unavailable")
    assert measurements[0]["status"] == "error"
    assert measurements[0]["error_type"] == "RuntimeError"
    assert measurements[0]["seconds"] >= 0
    assert summary(measurements)[0]["errors"] == 1


async def test_step_two_replays_step_one_without_embedding_or_graph_lookup(
    reuse_db, tmp_path, monkeypatch
):
    current = need()
    scope = context()
    identity = {"attempt_id": "fixture", "need": asdict(current), "context": asdict(scope)}
    target = {"need": current, "context": scope, "identity": identity}
    paths = {stage: tmp_path / f"step_{stage}.json" for stage in range(1, 5)}
    payload = EVIDENCE.dump_python([evidence()], mode="json")
    save(paths[1], target=identity, stage=1, payload=payload)
    adapter = SimpleNamespace(
        assess=AsyncMock(
            return_value=ResearchAssessmentDraft(
                result="sufficient",
                rationale="Reusable",
            )
        )
    )
    real_assess = probes.assess

    async def mocked_model(factory, need, items, context, *, timings):
        return await real_assess(
            factory, need, items, context, builder=AsyncMock(return_value=adapter), timings=timings
        )

    monkeypatch.setattr(probes, "assess", mocked_model)
    monkeypatch.setattr(probes, "lookup", AsyncMock(side_effect=RuntimeError("must not retrieve")))
    result = await live.run_step(2, factory=reuse_db, target=target, paths=paths, timings={})
    assert result["assessment"] == "sufficient"
    assert adapter.assess.await_count == 1
    probes.lookup.assert_not_called()
    replay = read(paths[2], target=identity, stage=2, parent=digest(payload))
    assert ASSESSMENT.validate_python(replay["payload"]).result == "sufficient"


async def test_pool_connection_is_free_during_gap_planning(reuse_db):
    async def external_planning(**_kwargs):
        async with reuse_db() as other:
            assert await asyncio.wait_for(other.scalar(text("SELECT 1")), timeout=1) == 1
        return [
            FollowUpNeedDraft(
                question="Vad ändrades senare?", why_needed="Gap", source_types=need().source_types
            )
        ]

    async def builder(session, **_kwargs):
        await session.execute(text("SELECT 1"))
        return SimpleNamespace(plan_follow_ups=external_planning)

    result = await probes.gaps(
        reuse_db,
        need(),
        [evidence()],
        ResearchAssessmentDraft(result="insufficient", rationale="Gap"),
        context=context(),
        builder=builder,
    )
    assert len(result) == 1
