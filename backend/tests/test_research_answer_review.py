"""Every provider and synthesized evidence use the same final-answer TTL boundary."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.database.answer_review import KnowledgeAnswerReview
from app.services.execution import list_evidence_items
from app.services.research import ResearchPlan, execute_attempt_research, research_evidence
from app.services.research.answer_review import capture_answer_reviews
from app.services.research.knowledge_question import research_question_key
from tests.test_research_execution import (
    RecordingSource,
    _created_attempt,
    _need,
    _router,
    db as db,
)


class Source(RecordingSource):
    async def research(self, need, context):
        self.calls += 1
        return [
            research_evidence(
                research_need_id=need.id,
                source_type=self.source_type,
                status="found",
                provider=self.provider_id,
                source_id="doc-" + self.source_type,
                excerpt=self.excerpt,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ]


async def test_generic_freeze_aggregates_sources_without_calling_jev(db, monkeypatch):
    from app.jev.system import HttpJevSystemOne

    async def forbidden(*args, **kwargs):
        raise AssertionError("TTL must not ask Jev inside research")

    monkeypatch.setattr(HttpJevSystemOne, "ask", forbidden)
    session, _factory = db
    customer, _run, attempt = await _created_attempt(session)
    router, sources = _router(Source("case_knowledge"), Source("customer_knowledge"))
    plan = ResearchPlan(needs=[_need("n1", "case_knowledge", "customer_knowledge")])
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
    )
    assert result.status == "ready"
    row = (await session.execute(select(KnowledgeAnswerReview))).scalar_one()
    assert row.customer_id == customer.id
    assert row.question_key == research_question_key(plan.needs[0].question)
    assert row.status == "awaiting_ttl" and row.ttl is None
    assert {e["source_type"] for e in row.answer_basis["evidence"]} == {
        "case_knowledge",
        "customer_knowledge",
    }
    assert len(row.evidence_refs) == 2
    assert row.answer_basis["assessments"]
    original = (row.id, row.created_at)
    await capture_answer_reviews(
        session, attempt_id=attempt.id, evidence_set_id=result.evidence_set_id
    )
    again = (await session.execute(select(KnowledgeAnswerReview))).scalar_one()
    assert (again.id, again.created_at) == original
    assert [s.calls for s in sources] == [1, 1]


async def test_empty_and_failed_sources_do_not_create_answer_versions(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session)
    router, _ = _router(RecordingSource("case_knowledge", mode="empty"))
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("n1", "case_knowledge")]),
        router=router,
    )
    assert result.status == "ready"
    assert list((await session.execute(select(KnowledgeAnswerReview))).scalars()) == []


async def test_excerpt_only_answers_do_not_require_claims_or_a_domain_interpreter(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session)
    router, _ = _router(Source("case_knowledge", excerpt="The answer initially"))
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("n1", "case_knowledge")]),
        router=router,
    )
    rows = list((await session.execute(select(KnowledgeAnswerReview))).scalars())
    assert len(rows) == 1
    # Both excerpt-only and derived evidence are represented without requiring claims.
    items = await list_evidence_items(session, result.evidence_set_id)
    assert items[0].domain_result_id is None
    assert rows[0].answer_basis["evidence"][0]["interpretation"] is None


async def test_synthesized_parent_uses_same_capture_path(db):
    from app.services.execution import (
        add_evidence_items,
        create_evidence_set,
        persist_runtime_needs,
    )
    from app.services.research.assessment import programmatic_assessment
    from app.services.research.followup import plan_from_runtime_needs
    from app.services.research.synthesis import derive_parent_answers
    from tests.test_research_synthesis import sample

    session, _factory = db
    _customer, run, attempt = await _created_attempt(session)
    needs, evidence = sample()
    assessment = programmatic_assessment(plan_from_runtime_needs(needs), evidence)
    derived = derive_parent_answers(needs, assessment, evidence)
    evidence_set = await create_evidence_set(session, run_id=run.id)
    await persist_runtime_needs(session, attempt_id=attempt.id, needs=needs)
    await add_evidence_items(session, evidence_set_id=evidence_set.id, items=derived)
    await capture_answer_reviews(session, attempt_id=attempt.id, evidence_set_id=evidence_set.id)
    row = (await session.execute(select(KnowledgeAnswerReview))).scalar_one()
    assert row.question == "Compare both results"
    assert row.answer_basis["evidence"][0]["source_type"] == "derived"
    assert "Verified statement a" in row.answer_basis["evidence"][0]["excerpt"]
    assert "Verified statement b" in row.answer_basis["evidence"][0]["excerpt"]
    assert row.status == "awaiting_ttl"
