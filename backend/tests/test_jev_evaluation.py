"""Content-addressed JEV reuse, tenant isolation, and single-flight."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import JevEvaluationArtifactRecord
from app.jev.evaluation import evaluation_key
from app.jev.service import build_request, evaluate_many, evaluate_system_one
from app.jev.singleflight import SingleFlight
from app.jev.system import (
    JevClientError,
    JevSystemOneResult,
    JevUsage,
    aclose_jev_http_client,
    open_jev_http_client,
)
from app.observability.research import research_obs_scope

_QUESTIONS = {"material_change": {"type": "noul", "instructions": "True if it matters."}}


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
        yield session
    await engine.dispose()


def _request(**overrides: object):
    fields: dict[str, object] = {
        "evaluator_id": "graph_relation_revalidation",
        "evaluator_version": "v1",
        "model": "jev-test",
        "questions": _QUESTIONS,
        "state": {"body": "same"},
        "security_scope": "customer:1",
        "content_hashes": {"claim:1": "hash-a"},
        "policy_version": "v1",
        "model_config": {"impact_threshold": "0.750000"},
    }
    fields.update(overrides)
    return build_request(**fields)  # type: ignore[arg-type]


class _CountingJev:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.hold = False

    async def ask(self, *, state, questions, model, timeout_seconds):
        del state, questions, model, timeout_seconds
        self.calls += 1
        if self.fail_times:
            self.fail_times -= 1
            raise JevClientError("timed out", category="timeout")
        if self.hold:
            self.started.set()
            await self.release.wait()
        return JevSystemOneResult(
            answers={"material_change": {"noul": 0.81}},
            model="jev-test",
            latency_ms=4.0,
            input_chars=3,
            usage=JevUsage(),
            raw={},
            http_ms=4.0,
        )


async def _evaluate(client: _CountingJev, request, session=None):
    return await evaluate_system_one(
        client,
        evaluator_id=request.evaluator_id,
        evaluator_version=request.evaluator_version,
        state=request.state,
        questions=request.questions,
        model=request.model,
        timeout_seconds=1,
        required_signals=("material_change",),
        policy_version=request.policy_version,
        security_scope=request.security_scope,
        session=session,
        content_hashes=request.content_hashes,
        model_config=request.model_config,
    )


@pytest.mark.asyncio
async def test_read_transaction_is_released_before_http(db):
    await db.scalar(select(func.count()).select_from(JevEvaluationArtifactRecord))
    assert db.in_transaction()
    client = _CountingJev()
    client.hold = True
    open_during: list[bool] = []

    async def ask(*, state, questions, model, timeout_seconds):
        open_during.append(db.in_transaction())
        return await _CountingJev.ask(
            client,
            state=state,
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    client.ask = ask  # type: ignore[method-assign]
    request = _request()
    task = asyncio.create_task(
        evaluate_many(
            client,
            [request],
            session=db,
            timeout_seconds=1,
            required_signals=("material_change",),
        )
    )
    await client.started.wait()
    client.release.set()
    await task
    assert open_during == [False]


@pytest.mark.asyncio
async def test_identical_evaluation_is_reused(db):
    client = _CountingJev()
    request = _request()
    with research_obs_scope() as stats:
        first = await _evaluate(client, request, db)
        second = await _evaluate(client, request, db)
    assert client.calls == 1
    assert first.answers == second.answers
    assert stats.jev_evaluation_requested == 2
    assert stats.jev_evaluation_executed == 1
    assert stats.jev_evaluation_reused == 1
    stored = await db.scalar(select(func.count()).select_from(JevEvaluationArtifactRecord))
    assert stored == 1


@pytest.mark.asyncio
async def test_changed_content_version_model_and_tenant_are_new_calls(db):
    client = _CountingJev()
    await _evaluate(client, _request(), db)
    await _evaluate(client, _request(content_hashes={"claim:1": "hash-b"}), db)
    await _evaluate(client, _request(evaluator_version="v2"), db)
    await _evaluate(client, _request(model_config={"impact_threshold": "0.900000"}), db)
    await _evaluate(client, _request(security_scope="customer:2"), db)
    assert client.calls == 5
    stored = list((await db.execute(select(JevEvaluationArtifactRecord))).scalars().all())
    scopes = {row.security_scope for row in stored}
    assert scopes == {"customer:1", "customer:2"}
    assert len(stored) == 5


@pytest.mark.asyncio
async def test_timeout_is_not_reused(db):
    client = _CountingJev(fail_times=1)
    request = _request()
    with pytest.raises(JevClientError):
        await _evaluate(client, request, db)
    await _evaluate(client, request, db)
    assert client.calls == 2
    stored = await db.scalar(select(func.count()).select_from(JevEvaluationArtifactRecord))
    assert stored == 1


@pytest.mark.asyncio
async def test_concurrent_identical_calls_share_one_outbound_request():
    client = _CountingJev()
    client.hold = True
    request = _request()

    async def call():
        return await _evaluate(client, request, session=None)

    first = asyncio.create_task(call())
    await client.started.wait()
    second = asyncio.create_task(call())
    for _ in range(20):
        await asyncio.sleep(0)
    client.release.set()
    results = await asyncio.gather(first, second)
    assert client.calls == 1
    assert results[0].answers == results[1].answers


@pytest.mark.asyncio
async def test_failed_singleflight_is_not_sticky():
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_failure() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        raise RuntimeError("down")

    flight = SingleFlight()
    leader = asyncio.create_task(flight.do("k", slow_failure))
    await started.wait()
    joined = asyncio.create_task(flight.do("k", slow_failure))
    for _ in range(20):
        await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(leader, joined, return_exceptions=True)
    assert all(isinstance(item, RuntimeError) for item in results)
    assert calls == 1

    async def recovered() -> str:
        return "up"

    assert await flight.do("k", recovered) == ("up", False)


@pytest.mark.asyncio
async def test_cancelling_one_waiter_leaves_the_shared_evaluation_running():
    started = asyncio.Event()
    release = asyncio.Event()

    async def work() -> str:
        started.set()
        await release.wait()
        return "ok"

    flight = SingleFlight()
    leader = asyncio.create_task(flight.do("k", work))
    await started.wait()
    joined = asyncio.create_task(flight.do("k", work))
    await asyncio.sleep(0)
    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
    release.set()
    assert await joined == ("ok", True)


def test_evaluation_key_includes_scope_and_content():
    left = evaluation_key(_request())
    right = evaluation_key(_request(security_scope="customer:9"))
    changed = evaluation_key(_request(content_hashes={"claim:1": "other"}))
    assert left != right
    assert left != changed


@pytest.mark.asyncio
async def test_http_client_is_reused_until_shutdown():
    await aclose_jev_http_client()
    first = open_jev_http_client()
    second = open_jev_http_client()
    assert first is second
    assert not first.is_closed
    await aclose_jev_http_client()
    assert first.is_closed
