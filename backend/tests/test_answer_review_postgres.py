"""Optional real PostgreSQL migration/locking test in a disposable schema."""

import asyncio
import importlib.util
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.knowledge.answer_review import (
    AnswerReviewDecision,
    enqueue_due_reviews,
    record_answer_review,
)

from app.services.knowledge.answer_review_classification import (
    claim_ttl_classification,
    finish_ttl_classification,
)

POSTGRES_URL = os.environ.get("TEST_ANSWER_REVIEW_POSTGRES_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not POSTGRES_URL, reason="local PG opt-in"),
]


async def test_postgres_migration_and_concurrent_candidate_workers(monkeypatch):
    schema = "answer_review_test_" + uuid4().hex
    admin = create_async_engine(POSTGRES_URL)
    engine = create_async_engine(POSTGRES_URL, connect_args={"options": f"-csearch_path={schema}"})
    path = Path(__file__).parents[1] / "alembic/versions/124_knowledge_answer_review_ttl.py"
    spec = importlib.util.spec_from_file_location("pg_answer_review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def upgrade(conn):
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()

    def downgrade(conn):
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.downgrade()

    try:
        async with admin.begin() as conn:
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE kunder (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("INSERT INTO kunder VALUES (1)"))
            await conn.run_sync(upgrade)
            assert await conn.scalar(
                text(
                    "SELECT relrowsecurity FROM pg_class "
                    "WHERE oid = 'knowledge_answer_reviews'::regclass"
                )
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory.begin() as session:
            ids = []
            for claim in ["a", "b", "c"]:
                ids.append(
                    await record_answer_review(
                        session,
                        customer_id=1,
                        question_key="q",
                        answer_basis={
                            "question": "Question?",
                            "assessments": [],
                            "evidence": [{"ref": claim, "source_type": "case_knowledge"}],
                        },
                        created_at=datetime(2026, 1, 31, tzinfo=UTC),
                    )
                )
        now = datetime(2027, 1, 1, tzinfo=UTC)
        await _classify_versions(factory, ids, now)

        async with factory.begin() as first:
            batch1 = await enqueue_due_reviews(first, now=now, limit=1)
            # First transaction deliberately remains open and owns its row lock.
            async with factory.begin() as second:
                batch2 = await asyncio.wait_for(
                    enqueue_due_reviews(second, now=now, limit=1),
                    timeout=3,
                )
            assert len(batch1) == len(batch2) == 1
            assert set(batch1).isdisjoint(batch2)
        async with factory.begin() as session:
            batch3 = await enqueue_due_reviews(session, now=now, limit=1)
            assert set(batch1 + batch2 + batch3) == set(ids)
            assert await enqueue_due_reviews(session, now=now) == []
        async with engine.begin() as conn:
            await conn.run_sync(downgrade)
            assert await conn.scalar(text("SELECT to_regclass('knowledge_answer_reviews')")) is None
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await admin.dispose()


async def _classify_versions(factory, ids, now):
    async with factory.begin() as first:
        claim1 = await claim_ttl_classification(first, now=now)
        async with factory.begin() as second:
            claim2 = await asyncio.wait_for(claim_ttl_classification(second, now=now), timeout=3)
        assert claim1["id"] != claim2["id"]
    async with factory.begin() as session:
        claim3 = await claim_ttl_classification(session, now=now)
        assert {claim["id"] for claim in [claim1, claim2, claim3]} == set(ids)
        assert await claim_ttl_classification(session, now=now) is None
        for claim in [claim1, claim2, claim3]:
            await finish_ttl_classification(
                session, claim=claim, decision=AnswerReviewDecision("soon")
            )
