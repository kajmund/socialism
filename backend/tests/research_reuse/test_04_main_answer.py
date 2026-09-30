import pytest
from sqlalchemy import select

from app.database.answer_review import KnowledgeAnswerReview
from app.services.execution import (
    add_evidence_items,
    attach_evidence_set,
    create_evidence_set,
    persist_research_assessment,
    persist_runtime_needs,
)
from app.services.research.answer_review import capture_answer_reviews
from app.services.research.assessment import ResearchAssessmentDraft, ResearchNeedAssessment
from app.services.research.followup import RuntimeResearchNeed
from tests.research_reuse.helpers import MAIN, attempt, evidence, need, pending_contract
from tests.research_reuse.probes import capture

pytestmark = pytest.mark.research_reuse


async def persisted_basis(factory, *, sufficient=True):
    async with factory.begin() as session:
        row = await attempt(session)
        evidence_set = await create_evidence_set(session, run_id=row.run_id)
        await attach_evidence_set(session, attempt_id=row.id, evidence_set_id=evidence_set.id)
        await persist_runtime_needs(
            session,
            attempt_id=row.id,
            needs=[
                RuntimeResearchNeed(
                    research_need_id="child",
                    question=need().question,
                    why_needed="Gap",
                    source_types=need().source_types,
                )
            ],
        )
        await add_evidence_items(
            session,
            evidence_set_id=evidence_set.id,
            items=[evidence(source_id="prop-1976"), evidence(source_id="prop-1995")],
        )
        await persist_research_assessment(
            session,
            attempt_id=row.id,
            evidence_set_id=evidence_set.id,
            evidence_fingerprint="two-sources",
            draft=ResearchAssessmentDraft(
                result="sufficient" if sufficient else "insufficient",
                rationale="Basis review",
                need_assessments=[
                    ResearchNeedAssessment(research_need_id="child", sufficient=sufficient)
                ],
            ),
        )
        return row.id, evidence_set.id


@pytest.mark.parametrize("sufficient", [True, False], ids=["complete", "partial"])
async def test_answer_basis_keeps_all_sources_and_actual_sufficiency(reuse_db, sufficient):
    attempt_id, set_id = await persisted_basis(reuse_db, sufficient=sufficient)
    async with reuse_db.begin() as session:
        await capture_answer_reviews(session, attempt_id=attempt_id, evidence_set_id=set_id)
        row = await session.scalar(select(KnowledgeAnswerReview))
        assert {item["source_id"] for item in row.answer_basis["evidence"]} == {
            "prop-1976",
            "prop-1995",
        }
        assert row.answer_basis["assessments"][0]["sufficient"] is sufficient
        original_id = row.id
        await capture_answer_reviews(session, attempt_id=attempt_id, evidence_set_id=set_id)
        assert list(await session.scalars(select(KnowledgeAnswerReview.id))) == [original_id]


async def test_live_capture_probe_rolls_back_its_real_database_writes(reuse_db):
    attempt_id, _set_id = await persisted_basis(reuse_db)
    result = await capture(reuse_db, attempt_id)
    assert result["captured_questions"] == [need().question]
    assert result["writes"] == "rolled_back"
    async with reuse_db() as session:
        assert list(await session.scalars(select(KnowledgeAnswerReview))) == []


@pending_contract("Punkt 4: freeze captures subquestions but omits the research objective's answer")
async def test_main_question_has_a_complete_reusable_answer_basis(reuse_db):
    attempt_id, set_id = await persisted_basis(reuse_db)
    async with reuse_db() as session:
        captured = await capture_answer_reviews(
            session, attempt_id=attempt_id, evidence_set_id=set_id
        )
        assert MAIN in [question for _key, question in captured]


@pending_contract("Punkt 4: main question and validated answer are not projected to Graph v2")
async def test_main_answer_is_projected_for_the_next_research(reuse_db):
    attempt_id, _set_id = await persisted_basis(reuse_db)
    result = await capture(reuse_db, attempt_id)
    assert result["contract_passed"], result
