"""Review reminders never expire evidence or scan the knowledge graph."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.answer_review import KnowledgeAnswerReview
from app.database.models import Kund
from app.jev.system import JevClientError
from app.services.knowledge.answer_review import (
    AnswerReviewDecision,
    complete_review,
    due_review_ids,
    enqueue_due_reviews,
    list_review_candidates,
    parse_review_decision,
    review_after,
    record_answer_review,
)

from app.services.knowledge.answer_review_classification import (
    claim_ttl_classification,
    finish_ttl_classification,
)


@pytest.mark.parametrize(
    ("created", "ttl", "expected"),
    [
        ("2026-01-31T12:30:00+00:00", "soon", "2026-04-30T12:30:00+00:00"),
        ("2025-08-31T12:30:00+00:00", "later", "2026-02-28T12:30:00+00:00"),
        ("2023-08-31T12:30:00+00:00", "later", "2024-02-29T12:30:00+00:00"),
        ("2026-10-31T12:30:00+00:00", "soon", "2027-01-31T12:30:00+00:00"),
        ("2026-01-31T14:30:00+02:00", "soon", "2026-04-30T12:30:00+00:00"),
    ],
)
def test_calendar_months(created, ttl, expected):
    assert review_after(datetime.fromisoformat(created), ttl) == datetime.fromisoformat(expected)


def test_never_is_not_an_expiry():
    assert review_after(datetime.now(UTC), "never") is None
    with pytest.raises(ValueError, match="timezone"):
        review_after(datetime(2026, 1, 1), "soon")


@pytest.mark.parametrize("ttl", ["soon", "later", "never"])
def test_parse_choice(ttl):
    assert parse_review_decision({"review_ttl": {"choice": ttl}}).ttl == ttl


@pytest.mark.parametrize("answer", [None, {}, {"choice": "tomorrow"}, {"choice": []}])
def test_invalid_jev_does_not_silently_become_never(answer):
    with pytest.raises(JevClientError, match="review_ttl"):
        parse_review_decision({"review_ttl": answer})


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        # No graph or evidence tables exist: queue processing cannot depend on them.
        await conn.run_sync(Kund.__table__.create)
        await conn.run_sync(KnowledgeAnswerReview.__table__.create)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([Kund(id=i, name=str(i), slug=str(i)) for i in [1, 2]])
        await session.flush()
        yield session
    await engine.dispose()


async def schedule(db, ttl="soon", *, customer_id=1, claims=None, created=None):
    refs = sorted(set(claims or ["claim-1"]))
    answer_id = await record_answer_review(
        db,
        customer_id=customer_id,
        question_key="question-key",
        answer_basis={
            "question": "What is known?",
            "assessments": [],
            "evidence": [{"ref": ref, "source_type": "case_knowledge"} for ref in refs],
        },
        created_at=created or datetime(2026, 1, 31, tzinfo=UTC),
    )
    status = await db.scalar(
        sa.select(KnowledgeAnswerReview.status).where(KnowledgeAnswerReview.id == answer_id)
    )
    if status == "awaiting_ttl":
        claim = await claim_ttl_classification(db, now=datetime(2100, 1, 1, tzinfo=UTC))
        assert claim["id"] == answer_id
        await finish_ttl_classification(db, claim=claim, decision=AnswerReviewDecision(ttl))
    return answer_id


async def test_display_question_changes_do_not_reset_version(db):
    original = await schedule(db)
    duplicate = await record_answer_review(
        db,
        customer_id=1,
        question_key="question-key",
        answer_basis={
            "question": "  WHAT is known?  ",
            "assessments": [],
            "evidence": [{"ref": "claim-1", "source_type": "case_knowledge"}],
        },
        created_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert duplicate == original
    row = await db.get(KnowledgeAnswerReview, original)
    assert row.review_after == datetime(2026, 4, 30)


async def test_due_boundary_never_and_bounded_idempotent_batches(db):
    soon = await schedule(db)
    later = await schedule(db, "later", claims=["claim-2"])
    never = await schedule(db, "never", claims=["claim-3"])
    assert await enqueue_due_reviews(db, now=datetime(2026, 4, 29, tzinfo=UTC)) == []
    assert await enqueue_due_reviews(db, now=datetime(2026, 4, 30, tzinfo=UTC)) == [soon]
    assert await enqueue_due_reviews(db, now=datetime(2026, 4, 30, tzinfo=UTC)) == []
    assert await enqueue_due_reviews(db, now=datetime(2026, 7, 31, tzinfo=UTC), limit=1) == [later]
    assert await enqueue_due_reviews(db, now=datetime(2030, 1, 1, tzinfo=UTC)) == []
    rows = await list_review_candidates(db, customer_id=1)
    assert {row.id for row in rows} == {soon, later}
    assert (await db.get(KnowledgeAnswerReview, never)).review_after is None


async def test_batch_progress_and_tenant_isolation(db):
    ids = [await schedule(db, claims=[str(i)]) for i in range(5)]
    other = await schedule(db, customer_id=2)
    now = datetime(2027, 1, 1, tzinfo=UTC)
    batches = [await enqueue_due_reviews(db, now=now, limit=2) for _ in range(4)]
    assert [len(batch) for batch in batches] == [2, 2, 2, 0]
    assert set(sum(batches, [])) == {*ids, other}
    assert {r.id for r in await list_review_candidates(db, customer_id=1)} == set(ids)
    assert [r.id for r in await list_review_candidates(db, customer_id=2)] == [other]
    assert not await complete_review(db, customer_id=1, answer_id=other)
    assert await complete_review(db, customer_id=2, answer_id=other)
    assert not await complete_review(db, customer_id=2, answer_id=other)


async def test_reuse_does_not_reset_clock_or_reopen_completed_version(db):
    original = await schedule(db, claims=["b", "a"])
    assert await schedule(db, "never", claims=["a", "b", "a"]) == original
    row = await db.get(KnowledgeAnswerReview, original)
    assert row.ttl == "soon"
    assert row.review_after == datetime(2026, 4, 30)
    now = datetime(2027, 1, 1, tzinfo=UTC)
    assert await enqueue_due_reviews(db, now=now) == [original]
    assert await complete_review(db, customer_id=1, answer_id=original)
    assert await schedule(db, claims=["a", "b"], created=now) == original
    assert await enqueue_due_reviews(db, now=now) == []
    new_version = await schedule(db, claims=["a", "b", "c"], created=now)
    assert new_version != original


async def test_due_query_uses_covering_index_without_sort_or_graph_scan(db):
    sql = str(
        due_review_ids(datetime(2027, 1, 1, tzinfo=UTC), 10).compile(
            dialect=db.get_bind().dialect,
            compile_kwargs={"literal_binds": True},
        )
    )
    rows = (await db.execute(sa.text("EXPLAIN QUERY PLAN " + sql))).all()
    plan = " ".join(str(row) for row in rows)
    assert "SEARCH knowledge_answer_reviews USING COVERING INDEX ix_answer_review_due" in plan
    assert "SCAN" not in plan
    assert "TEMP B-TREE" not in plan
    pg_sql = str(due_review_ids(datetime.now(UTC), 10).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in pg_sql


@pytest.mark.parametrize("limit", [0, -1, 501])
async def test_bounds(db, limit):
    with pytest.raises(ValueError, match="batch limit"):
        await enqueue_due_reviews(db, limit=limit)
    with pytest.raises(ValueError, match="batch limit"):
        await list_review_candidates(db, customer_id=1, limit=limit)


def test_migration_roundtrip(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/124_knowledge_answer_review_ttl.py"
    spec = importlib.util.spec_from_file_location("answer_review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE kunder (id INTEGER PRIMARY KEY)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()
        inspector = sa.inspect(conn)
        assert {i["name"] for i in inspector.get_indexes("knowledge_answer_reviews")} == {
            "ix_answer_review_due",
            "ix_answer_review_customer",
            "ix_answer_review_classify",
        }
        assert {c["name"] for c in inspector.get_columns("knowledge_answer_reviews")} == {
            c.name for c in KnowledgeAnswerReview.__table__.columns
        }
        conn.execute(sa.text("INSERT INTO kunder VALUES (1)"))
        conn.execute(
            KnowledgeAnswerReview.__table__.insert().values(
                id="answer",
                customer_id=1,
                question_key="q",
                question="Question?",
                evidence_refs=["claim"],
                answer_basis={},
                ttl="never",
                created_at=datetime.now(UTC),
                status="scheduled",
            )
        )
        migration.downgrade()
        assert "knowledge_answer_reviews" not in sa.inspect(conn).get_table_names()
    engine.dispose()


async def test_llm_wording_does_not_mint_new_version(db):
    """Same cited evidence + scope is one version, however the LLM words it."""

    def basis(assessment, interpretation):
        return {
            "question": "What is known?",
            "scope": {"module": "rattsunderlag", "case_id": 5},
            "assessments": [{"summary": assessment}],
            "evidence": [
                {"ref": "ref-a", "source_type": "case_knowledge", "interpretation": interpretation}
            ],
        }

    first = await record_answer_review(
        db, customer_id=1, question_key="q", answer_basis=basis("Sufficient.", "Reading one"),
        created_at=datetime(2026, 1, 31, tzinfo=UTC),
    )
    again = await record_answer_review(
        db, customer_id=1, question_key="q", answer_basis=basis("Adequate.", "Reading two"),
        created_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    other_case = await record_answer_review(
        db, customer_id=1, question_key="q",
        answer_basis={**basis("Sufficient.", "Reading one"), "scope": {"module": "rattsunderlag", "case_id": 6}},
    )
    new_evidence = await record_answer_review(
        db, customer_id=1, question_key="q",
        answer_basis={**basis("Sufficient.", "Reading one"),
                      "evidence": [{"ref": "ref-a", "source_type": "x"}, {"ref": "ref-b", "source_type": "x"}]},
    )
    assert first == again
    assert len({first, other_case, new_evidence}) == 3
    row = await db.get(KnowledgeAnswerReview, first)
    assert row.created_at.replace(tzinfo=UTC) == datetime(2026, 1, 31, tzinfo=UTC)
