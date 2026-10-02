"""Production-shaped expert questions join their child needs by canonical identity."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database.models import Persona, ResearchNeedExecution, ResearchRuntimeNeed
from app.services.execution import (
    add_evidence_items,
    attach_evidence_set,
    claim_freeze_evidence_set,
    create_attempt,
    create_evidence_set,
    persist_research_assessment,
)
from app.services.research.assessment import ResearchAssessmentDraft, ResearchNeedAssessment
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    create_general_question,
    create_specific_question,
)
from app.services.research.models import research_evidence
from tests.conftest import TEST_CUSTOMER_ID
from tests.test_research_overview_api import _runtime_need


async def setup_parent(client, factory):
    response = await client.post(
        "/execution/runs",
        json={
            "customer_id": TEST_CUSTOMER_ID,
            "module": "dd",
            "title": "Expertchat",
            "context": {},
        },
    )
    assert response.status_code == 201
    async with factory.begin() as session:
        parent = await create_attempt(
            session,
            run_id=response.json()["id"],
            attempt_type="expert_chat_question_dag",
            input_snapshot={},
        )
        specific = await create_specific_question(
            session,
            run_id=parent.run_id,
            text="Klausulen i mitt avtal",
            context={},
            origin_kind="expert_chat",
        )
        expert = (
            await session.scalars(
                select(Persona)
                .where(
                    Persona.customer_id == TEST_CUSTOMER_ID,
                    Persona.kind == "expert",
                )
                .limit(1)
            )
        ).one()
    return parent, specific, expert


async def setup_question(session, parent, specific, expert, *, text):
    return await create_general_question(
        session,
        attempt_id=parent.id,
        specific_question_id=specific.id,
        draft=GeneralQuestionDraft(
            question=text,
            why_needed="Bedöm klausulens skälighet.",
            raised_by_expert_ids=[expert.id],
            assigned_expert_id=expert.id,
        ),
    )


async def add_child_basis(session, parent, question, sufficient, *, need_id="research-main"):
    child = await create_attempt(
        session,
        run_id=parent.run_id,
        parent_attempt_id=parent.id,
        attempt_type="research_question",
        input_snapshot={"research_question_id": question.id},
    )
    need = _runtime_need(child.id, need_id, "Olika text men samma kanoniska identitet")
    need.knowledge_question_id = question.knowledge_question_id
    need.why_needed = '{"context":{"why_needed":"Bedöm klausulens skälighet."}}'
    session.add(need)
    evidence_set = await create_evidence_set(
        session,
        run_id=parent.run_id,
        created_from_attempt_id=child.id,
    )
    item = research_evidence(
        research_need_id=need_id,
        source_type="swedish_case_law",
        status="found",
        title="HD: " + question.id,
        excerpt="HD prövade oskälighet i detta avtal.",
        source_url="https://example.test/hd/" + question.id,
        provider="graph_v2",
    )
    await add_evidence_items(session, evidence_set_id=evidence_set.id, items=[item])
    await claim_freeze_evidence_set(session, evidence_set.id)
    await attach_evidence_set(session, attempt_id=child.id, evidence_set_id=evidence_set.id)
    await persist_research_assessment(
        session,
        attempt_id=child.id,
        evidence_set_id=evidence_set.id,
        evidence_fingerprint=question.id,
        draft=ResearchAssessmentDraft(
            result="sufficient" if sufficient else "insufficient",
            rationale="Bedömt.",
            need_assessments=[
                ResearchNeedAssessment(
                    research_need_id=need_id,
                    sufficient=sufficient,
                    supporting_evidence_ids=[item.evidence_id],
                    missing_or_weak="En avgränsad lucka.",
                )
            ],
        ),
    )
    session.add(
        ResearchNeedExecution(
            id=uuid4().hex, attempt_id=child.id, research_need_id=need_id, status="completed"
        )
    )
    child.status = "ready"
    question.execution_attempt_id = child.id
    question.status = "completed"
    return child, item


@pytest.mark.parametrize("sufficient", [True, False], ids=["answered", "insufficient"])
async def test_expert_question_has_one_card_with_its_real_sources_and_assessment(
    client_db, sufficient
):
    client, factory = client_db
    parent, specific, expert = await setup_parent(client, factory)
    async with factory.begin() as session:
        question = await setup_question(
            session, parent, specific, expert, text="Hur tillämpas 36 §?"
        )
        assert question.runtime_need_id is None
        child, item = await add_child_basis(session, parent, question, sufficient)
    body = (await client.get(f"/execution/attempts/{parent.id}/research-overview")).json()
    assert body["counts"]["total"] == 1
    assert body["counts"]["unanswered"] == 0
    assert body["phase"] == ("completed" if sufficient else "completed_with_gaps")
    (row,) = body["questions"]
    assert row["id"] == question.id
    assert row["status"] == ("answered" if sufficient else "insufficient")
    assert row["child_attempt_id"] == child.id
    assert row["raised_by"][0]["id"] == expert.id
    assert row["assigned_to"]["id"] == expert.id
    assert row["why_needed"] == "Bedöm klausulens skälighet."
    assert row["source_count"] == 1
    assert row["sources"][0]["original_evidence_id"] == item.evidence_id
    assert row["sources"][0]["id"] != item.evidence_id
    assert row["need_assessment"]["sufficient"] is sufficient
    assert row["need_assessment"]["supporting_evidence_ids"] == [item.evidence_id]
    assert row["need_assessment"]["missing_or_weak"] == "En avgränsad lucka."


async def test_child_local_need_ids_never_hide_another_child_or_its_followups(client_db):
    client, factory = client_db
    parent, specific, expert = await setup_parent(client, factory)
    async with factory.begin() as session:
        question_a = await setup_question(
            session, parent, specific, expert, text="Hur tillämpas 36 §?"
        )
        question_b = await setup_question(
            session, parent, specific, expert, text="Hur tillämpas 33 §?"
        )
        child_a, evidence_a = await add_child_basis(session, parent, question_a, True)
        child_b, evidence_b = await add_child_basis(session, parent, question_b, False)
        session.add(_runtime_need(child_b.id, "followup-1", "Vilken senare praxis saknas?"))
        # This explicit id is from a different execution; it is not the question identity.
        question_a.runtime_need_id = "followup-1"
    body = (await client.get(f"/execution/attempts/{parent.id}/research-overview")).json()
    assert body["counts"]["total"] == 3
    by_id = {row["id"]: row for row in body["questions"]}
    for question, child, evidence in (
        (question_a, child_a, evidence_a),
        (question_b, child_b, evidence_b),
    ):
        row = by_id[question.id]
        assert row["sources"][0]["original_evidence_id"] == evidence.evidence_id
        assert row["child_attempt_id"] == child.id
        assert row["need_assessment"]["research_need_id"] == "research-main"
    followup = by_id[f"runtime-need:{child_b.id}:followup-1"]
    assert followup["status"] == "waiting"
    assert followup["source_count"] == 0
    assert followup["question"] == "Vilken senare praxis saknas?"


async def test_other_child_question_evidence_cannot_answer_unbound_expert_question(client_db):
    client, factory = client_db
    parent, specific, expert = await setup_parent(client, factory)
    async with factory.begin() as session:
        question = await setup_question(
            session, parent, specific, expert, text="Hur tillämpas 36 §?"
        )
        child, _item = await add_child_basis(session, parent, question, True)
        need = (
            await session.scalars(
                select(ResearchRuntimeNeed).where(
                    ResearchRuntimeNeed.attempt_id == child.id,
                )
            )
        ).one()
        need.knowledge_question_id = None
    body = (await client.get(f"/execution/attempts/{parent.id}/research-overview")).json()
    assert body["counts"]["total"] == 2
    row = next(r for r in body["questions"] if r["id"] == question.id)
    assert row["status"] == "unanswered"
    assert row["sources"] == []
    assert row["need_assessment"] is None
