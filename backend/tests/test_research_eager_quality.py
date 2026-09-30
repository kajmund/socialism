"""Fas 5 — eager evidence quality after each need persist."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import ExecutionAttempt, Kund
from app.observability.events import EVENT_PAYLOAD_ATTR
from app.observability.research import EVENT_RESEARCH_EXECUTION_SUMMARY
from app.services.execution import (
    create_attempt,
    create_run,
    list_evidence_items,
    list_evidence_quality,
    list_need_executions,
)
from app.services.research import (
    ResearchNeed,
    ResearchPlan,
    execute_attempt_research,
    research_evidence,
)
from app.services.research.quality import EvidenceRelevanceJudgment
from tests.test_research_execution import RecordingSource, _need, _router


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session, factory
    await engine.dispose()


@pytest.fixture
async def file_db(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/research.sqlite",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session, factory
    await engine.dispose()


async def _created_attempt(session: AsyncSession, *, slug: str) -> ExecutionAttempt:
    kund = Kund(name=slug, slug=slug, available_modules=["dd"])
    session.add(kund)
    await session.flush()
    run = await create_run(
        session,
        customer_id=kund.id,
        module="dd",
        title="Kvalitet",
        context={"case_id": "case-1"},
    )
    return await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
    )


def _quality_tuple(row: object) -> tuple[object, ...]:
    flags = row.flags if isinstance(row.flags, list) else []
    return (
        row.evidence_set_item_id,
        row.original_evidence_id,
        row.scoring_policy_version,
        row.authority,
        row.relevance,
        row.currentness,
        row.source_nature,
        row.source_timestamp,
        row.independence_key,
        row.independent_source_count,
        tuple(
            (item.get("code"), item.get("detail"))
            for item in flags
            if isinstance(item, dict)
        ),
        row.rationale,
        dict(row.declared_signals or {}),
        row.model_provider,
        row.model_name,
        row.model_version,
    )


class FixedRelevance:
    async def judge(self, need: ResearchNeed, item: object) -> EvidenceRelevanceJudgment:
        del need, item
        return EvidenceRelevanceJudgment(
            relevance="high",
            model_provider="test",
            model_name="fixed",
            model_version="1",
        )


class FailThenSucceed:
    def __init__(self) -> None:
        self.calls = 0

    async def judge(self, need: ResearchNeed, item: object) -> EvidenceRelevanceJudgment:
        del need, item
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("eager boom")
        return EvidenceRelevanceJudgment(
            relevance="medium",
            model_provider="test",
            model_name="recovered",
        )


@pytest.mark.asyncio
async def test_eager_plus_barrier_matches_barrier_only(db, monkeypatch):
    session, factory = db
    attempt = await _created_attempt(session, slug="same-rows")
    router, _ = _router(RecordingSource("case_knowledge"))
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    assessor = FixedRelevance()

    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
        session_factory=factory,
        relevance_assessor=assessor,
    )
    eager_rows = await list_evidence_quality(session, result.evidence_set_id)

    async def skip_eager(**kwargs: object) -> None:
        del kwargs

    monkeypatch.setattr(
        "app.services.research.execution.score_need_quality_eager",
        skip_eager,
    )
    other = await _created_attempt(session, slug="barrier-only")
    barrier_only = await execute_attempt_research(
        session,
        attempt_id=other.id,
        research_plan=plan,
        router=router,
        session_factory=factory,
        relevance_assessor=FixedRelevance(),
    )
    barrier_rows = await list_evidence_quality(session, barrier_only.evidence_set_id)
    assert [_quality_tuple(row)[2:] for row in eager_rows] == [
        _quality_tuple(row)[2:] for row in barrier_rows
    ]
    assert {row.relevance for row in eager_rows} == {"high"}


@pytest.mark.asyncio
async def test_fast_need_quality_exists_before_slow_need_completes(file_db):
    session, factory = file_db
    attempt = await _created_attempt(session, slug="eager-race")
    attempt_id = attempt.id
    release_slow = asyncio.Event()
    fast_quality = asyncio.Event()
    fast_retrieving = asyncio.Event()

    class SplitSource:
        source_type = "case_knowledge"
        provider_id = "fake"

        async def research(self, need: ResearchNeed, context: object):
            del context
            if need.id == "fast":
                fast_retrieving.set()
            if need.id == "slow":
                await release_slow.wait()
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type="case_knowledge",
                    status="found",
                    excerpt=f"hit-{need.id}",
                    locator=need.id,
                    retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
                )
            ]

    async def watch() -> None:
        await fast_retrieving.wait()
        while True:
            async with factory() as other:
                row = await other.get(ExecutionAttempt, attempt_id)
                if row is not None and row.evidence_set_id:
                    items = await list_evidence_items(other, row.evidence_set_id)
                    quality = await list_evidence_quality(other, row.evidence_set_id)
                    executions = await list_need_executions(other, attempt_id)
                    by_need = {item.research_need_id: item.status for item in executions}
                    fast_ids = {
                        item.id for item in items if item.research_need_id == "fast"
                    }
                    if fast_ids and any(
                        qrow.evidence_set_item_id in fast_ids for qrow in quality
                    ):
                        assert by_need["fast"] == "completed"
                        assert by_need["slow"] in {"pending", "running"}
                        assert not any(
                            item.research_need_id == "slow" for item in items
                        )
                        fast_quality.set()
                        return
            await asyncio.sleep(0.01)

    router, _ = _router(SplitSource())
    watch_task = asyncio.create_task(watch())
    exec_task = asyncio.create_task(
        execute_attempt_research(
            session,
            attempt_id=attempt_id,
            research_plan=ResearchPlan(
                needs=[
                    _need('fast', 'case_knowledge', question=f"Vad gäller skattesatsen för {'fast'}?"),
                    _need('slow', 'case_knowledge', question=f"Vad gäller skattesatsen för {'slow'}?"),
                ]
            ),
            router=router,
            session_factory=factory,
            concurrency=2,
        )
    )
    await asyncio.wait_for(fast_quality.wait(), timeout=3)
    release_slow.set()
    result = await exec_task
    await watch_task
    assert result.status == "ready"


@pytest.mark.asyncio
async def test_eager_assessor_failure_does_not_fail_need(db, caplog):
    session, factory = db
    attempt = await _created_attempt(session, slug="eager-fail")
    router, _ = _router(RecordingSource("case_knowledge"))
    assessor = FailThenSucceed()
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
        session_factory=factory,
        relevance_assessor=assessor,
    )
    assert result.status == "ready"
    executions = await list_need_executions(session, attempt.id)
    assert {row.status for row in executions} == {"completed"}
    quality = await list_evidence_quality(session, result.evidence_set_id)
    assert quality
    assert {row.relevance for row in quality} == {"medium"}
    assert "research_eager_quality_failed" in caplog.text


@pytest.mark.asyncio
async def test_successful_eager_leaves_no_barrier_quality_items(db, caplog):
    session, factory = db
    attempt = await _created_attempt(session, slug="eager-all")
    router, _ = _router(RecordingSource("case_knowledge"))
    with caplog.at_level("INFO"):
        result = await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=router,
            session_factory=factory,
        )
    assert result.status == "ready"
    summary = None
    for record in caplog.records:
        extra = getattr(record, EVENT_PAYLOAD_ATTR, None)
        if extra and extra.get("event", {}).get("name") == EVENT_RESEARCH_EXECUTION_SUMMARY:
            summary = extra
    assert summary is not None
    research = summary["research"]
    assert research["eager_quality_items"] >= 1
    assert research["barrier_quality_items"] == 0


class SharedPassageSource:
    source_type = "case_knowledge"
    provider_id = "fake"

    async def research(self, need: ResearchNeed, context: object):
        del context
        return [
            research_evidence(
                research_need_id=need.id,
                source_type="case_knowledge",
                status="found",
                title="Kommunens skattesats",
                excerpt="samma passage",
                locator="p1",
                source_id="doc-brief",
                source_url="https://example.test/brief.pdf",
                provider="fake",
                retrieved_at=datetime(2026, 4, 1, tzinfo=UTC),
            )
        ]


@pytest.mark.asyncio
async def test_linked_passage_keeps_first_need_quality_row(db):
    session, factory = db
    attempt = await _created_attempt(session, slug="linked-quality")
    router, _ = _router(SharedPassageSource())
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(
            needs=[
                _need('first', 'case_knowledge', question=f"Vad gäller skattesatsen för {'first'}?"),
                _need('second', 'case_knowledge', question=f"Vad gäller skattesatsen för {'second'}?"),
            ]
        ),
        router=router,
        session_factory=factory,
        relevance_assessor=FixedRelevance(),
        concurrency=1,
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    quality = await list_evidence_quality(session, result.evidence_set_id)
    assert len(items) == 1
    assert items[0].research_need_id == "first"
    assert {link.research_need_id for link in items[0].need_links} == {"first", "second"}
    assert [row.evidence_set_item_id for row in quality] == [items[0].id]
    assert {row.relevance for row in quality} == {"high"}
    assert {row.model_name for row in quality} == {"fixed"}


@pytest.mark.asyncio
async def test_graph_upsert_runs_before_eager_quality(db, monkeypatch):
    session, factory = db
    attempt = await _created_attempt(session, slug="graph-before-eager")
    order: list[str] = []

    async def graph(*args: object, **kwargs: object) -> None:
        del args, kwargs
        order.append("graph")

    async def eager(*args: object, **kwargs: object) -> None:
        del args, kwargs
        order.append("eager")

    monkeypatch.setattr(
        "app.services.research.execution.commit_persisted_evidence",
        graph,
    )
    monkeypatch.setattr(
        "app.services.research.execution.score_need_quality_eager",
        eager,
    )
    router, _ = _router(RecordingSource("case_knowledge"))
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
        session_factory=factory,
    )
    assert result.status == "ready"
    assert order == ["graph", "eager"]
