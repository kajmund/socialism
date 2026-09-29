"""The worker retries durable graph projection failures without losing research."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.graph_v2 import GraphIngestWork
from app.database.models import Kund
from app.services.graph_v2.outbox import process_graph_work


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
    await engine.dispose()
