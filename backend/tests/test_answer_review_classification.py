"""TTL failures and retries are isolated from research and release DB connections."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database.answer_review import KnowledgeAnswerReview
from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.knowledge.answer_review import AnswerReviewDecision, record_answer_review
from app.services.knowledge.answer_review_classification import (
    claim_ttl_classification,
    classification_state,
    classify_pending_reviews,
    finish_ttl_classification,
)
from tests.test_answer_review import db as db


def basis(*source_types):
    return {
        "question": "What is known?",
        "assessments": [{"sufficient": True}],
        "evidence": [
            {"ref": source, "source_type": source, "excerpt": "Supported answer"}
            for source in source_types
        ],
    }


class FakeJev:
    def __init__(self, choice="later", error=None):
        self.choice = choice
        self.error = error
        self.calls = []

    async def ask(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return JevSystemOneResult(
            answers={"review_ttl": {"choice": self.choice}},
            model="jev-test",
            latency_ms=1,
            input_chars=100,
            usage=JevUsage(),
            raw={},
        )


async def pending(db, sources=("case_knowledge", "customer_knowledge")):
    answer_id = await record_answer_review(
        db,
        customer_id=1,
        question_key="q",
        answer_basis=basis(*sources),
        created_at=datetime(2026, 1, 31, tzinfo=UTC),
    )
    await db.commit()
    return answer_id


@pytest.mark.parametrize("choice", ["soon", "later", "never"])
async def test_worker_classifies_aggregated_basis_once(db, choice):
    answer_id = await pending(db)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    jev = FakeJev(choice)
    result = await classify_pending_reviews(factory, jev=jev)
    assert result == {"classified_ids": [answer_id], "failed": []}
    assert len(jev.calls) == 1
    state = jev.calls[0]["state"]
    assert state["source_types"] == ["case_knowledge", "customer_knowledge"]
    assert len(state["evidence"]) == 2
    row = await db.get(KnowledgeAnswerReview, answer_id)
    assert row.ttl == choice
    assert row.status == "scheduled"
    assert (
        row.review_after
        == {"soon": datetime(2026, 4, 30), "later": datetime(2026, 7, 31), "never": None}[choice]
    )
    assert await classify_pending_reviews(factory, jev=jev) == {"classified_ids": [], "failed": []}
    assert len(jev.calls) == 1


@pytest.mark.parametrize("error", ["timeout", "invalid_choice"])
async def test_failed_ttl_stays_pending_and_retries_later(db, error):
    answer_id = await pending(db)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    jev = FakeJev(
        choice="bad",
        error=JevClientError("timeout", category="timeout") if error == "timeout" else None,
    )
    result = await classify_pending_reviews(factory, jev=jev)
    assert not result["classified_ids"]
    assert result["failed"][0]["id"] == answer_id
    row = await db.get(KnowledgeAnswerReview, answer_id)
    assert row.status == "awaiting_ttl"
    assert row.ttl is None and row.review_after is None
    assert row.last_error in {"timeout", "schema_validation"}
    assert await classify_pending_reviews(factory, jev=jev) == {"classified_ids": [], "failed": []}
    assert len(jev.calls) == 1
    claim = await claim_ttl_classification(db, now=datetime.now(UTC) + timedelta(minutes=6))
    assert await finish_ttl_classification(db, claim=claim, decision=AnswerReviewDecision("soon"))


async def test_expired_lease_is_reclaimable_and_old_worker_cannot_overwrite(db):
    answer_id = await pending(db)
    now = datetime.now(UTC)
    old = await claim_ttl_classification(db, now=now)
    assert await claim_ttl_classification(db, now=now) is None
    new = await claim_ttl_classification(db, now=now + timedelta(minutes=3))
    assert old["id"] == new["id"] == answer_id
    assert old["classification_token"] != new["classification_token"]
    assert not await finish_ttl_classification(
        db, claim=old, decision=AnswerReviewDecision("never")
    )
    assert await finish_ttl_classification(db, claim=new, decision=AnswerReviewDecision("later"))
    row = await db.scalar(
        select(KnowledgeAnswerReview).where(KnowledgeAnswerReview.id == answer_id)
    )
    assert row.ttl == "later"


def test_compaction_is_explicit_and_source_independent():
    state = classification_state(basis(*(f"source-{n}" for n in range(50))))
    assert state["evidence_count"] == 50
    assert len(state["source_types"]) == 50
    assert state["omitted_evidence_count"] > 0
    assert state["detail_is_compacted"] is True


async def test_no_database_connection_is_held_during_jev(db):
    await pending(db)
    active = 0

    def checkout(*args):
        nonlocal active
        active += 1

    def checkin(*args):
        nonlocal active
        active -= 1

    class CheckedJev(FakeJev):
        async def ask(self, **kwargs):
            assert active == 0
            return await super().ask(**kwargs)

    engine = db.bind.sync_engine
    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        result = await classify_pending_reviews(async_sessionmaker(db.bind), jev=CheckedJev())
        assert len(result["classified_ids"]) == 1
        assert active == 0
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)


async def test_classification_claim_uses_the_queue_index(db):
    await pending(db)
    plans = []

    def inspect_plan(conn, cursor, statement, parameters, *_unused):
        if statement.startswith("WITH ttl_batch"):
            plans.extend(conn.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).all())

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", inspect_plan)
    try:
        assert await claim_ttl_classification(db, now=datetime.now(UTC))
    finally:
        event.remove(engine, "before_cursor_execute", inspect_plan)
    plan = " ".join(str(row) for row in plans)
    assert "SEARCH knowledge_answer_reviews USING COVERING INDEX ix_answer_review_classify" in plan
    assert "SCAN knowledge_answer_reviews" not in plan
