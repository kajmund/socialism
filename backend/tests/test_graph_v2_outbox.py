"""The worker retries durable graph projection failures without losing research."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.graph_v2 import GraphIngestWork
from app.database.models import Kund
from app.services.graph_v2.outbox import enqueue_legal_graph, process_graph_work
from app.services.knowledge.claims import KnowledgeClaim


class FakeEmbedder:
    model = "test"
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


async def test_failed_projection_keeps_retryable_payload(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/outbox.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        session.add(GraphIngestWork(
            id="broken", customer_id=1, scope_key="customer:1",
            payload={"claims": [{"bad": "shape"}]}, status="pending", attempts=0,
        ))
    result = await process_graph_work(factory, embedder=FakeEmbedder())
    assert result == {"completed": 0, "failed": 1}
    async with factory() as session:
        work = await session.scalar(select(GraphIngestWork))
        assert work.status == "pending"
        assert work.attempts == 1
        assert work.last_error
        assert work.retry_at is not None
        work.retry_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert await process_graph_work(factory, embedder=FakeEmbedder()) == {
        "completed": 0, "failed": 1,
    }
    async with factory() as session:
        work = await session.get(GraphIngestWork, "broken")
        assert work.status == "pending" and work.attempts == 2
    await engine.dispose()


async def test_outbox_key_distinguishes_new_facts_on_same_research_need(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/outbox-identity.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        await session.flush()
        first = KnowledgeClaim("first", 1, "legal.outcome", {"value": True}, ("unit",))
        second = KnowledgeClaim("second", 1, "legal.outcome", {"value": False}, ("unit",))
        common = dict(customer_id=1, research_need_id="research_1", entities=(),
                      module="politik")
        first_id = await enqueue_legal_graph(session, claims=[first], **common)
        second_id = await enqueue_legal_graph(session, claims=[second], **common)
        assert first_id != second_id
        assert await enqueue_legal_graph(session, claims=[first], **common) == first_id
        assert await session.scalar(select(func.count()).select_from(GraphIngestWork)) == 2
        assert (await session.get(GraphIngestWork, first_id)).payload["module"] == "politik"
    await engine.dispose()
