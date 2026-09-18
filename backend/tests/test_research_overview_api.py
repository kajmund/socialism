from __future__ import annotations

from sqlalchemy import select

from app.database.models import Persona
from app.services.execution import (
    add_evidence_items,
    attach_evidence_set,
    claim_freeze_evidence_set,
    create_attempt,
    create_evidence_set,
    mark_ready,
)
from app.services.research.models import research_evidence
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    add_question_dependency,
    create_general_question,
    create_specific_question,
)
from tests.conftest import TEST_CUSTOMER_ID


async def test_empty_research_is_only_not_needed_after_attempt_is_ready(client_db):
    client, factory = client_db
    run_response = await client.post(
        "/execution/runs",
        json={
            "customer_id": TEST_CUSTOMER_ID,
            "module": "expertgranskning",
            "title": "Avtalsgranskning",
            "context": {},
        },
    )
    run = run_response.json()
    async with factory() as session:
        parent = await create_attempt(
            session,
            run_id=run["id"],
            attempt_type="generic_panel",
            configuration_snapshot={},
            input_snapshot={},
        )
        await session.commit()

    response = await client.get(f"/execution/attempts/{parent.id}/research-overview")
    assert response.json()["phase"] == "researching"

    async with factory() as session:
        evidence_set = await create_evidence_set(
            session,
            run_id=run["id"],
            created_from_attempt_id=parent.id,
        )
        await claim_freeze_evidence_set(session, evidence_set.id)
        await attach_evidence_set(
            session,
            attempt_id=parent.id,
            evidence_set_id=evidence_set.id,
        )
        await mark_ready(session, parent.id)
        await session.commit()

    response = await client.get(f"/execution/attempts/{parent.id}/research-overview")
    body = response.json()
    assert body["phase"] == "not_needed"
    assert body["counts"]["total"] == 0
    assert body["questions"] == []


async def test_research_overview_aggregates_question_graph_and_sources(client_db):
    client, factory = client_db
    run_response = await client.post(
        "/execution/runs",
        json={
            "customer_id": TEST_CUSTOMER_ID,
            "module": "expertgranskning",
            "title": "Avtalsgranskning",
            "context": {},
        },
    )
    run = run_response.json()
    async with factory() as session:
        parent = await create_attempt(
            session,
            run_id=run["id"],
            attempt_type="generic_panel",
            configuration_snapshot={},
            input_snapshot={},
        )
        expert = (
            await session.execute(
                select(Persona)
                .where(
                    Persona.customer_id == TEST_CUSTOMER_ID,
                    Persona.kind == "expert",
                )
                .limit(1)
            )
        ).scalar_one()
        specific = await create_specific_question(
            session,
            run_id=run["id"],
            text="Vad innebär klausul 2?",
            context={},
            origin_kind="expertgranskning",
        )
        answered = await create_general_question(
            session,
            attempt_id=parent.id,
            specific_question_id=specific.id,
            draft=GeneralQuestionDraft(
                question="Vilka rekvisit gäller?",
                raised_by_expert_ids=[expert.id],
                assigned_expert_id=expert.id,
            ),
        )
        waiting = await create_general_question(
            session,
            attempt_id=parent.id,
            specific_question_id=specific.id,
            draft=GeneralQuestionDraft(
                question="Hur tillämpas rekvisiten i praxis?",
                raised_by_expert_ids=[expert.id],
                assigned_expert_id=expert.id,
            ),
        )
        await add_question_dependency(
            session,
            question_id=waiting.id,
            depends_on_question_id=answered.id,
        )
        child = await create_attempt(
            session,
            run_id=run["id"],
            parent_attempt_id=parent.id,
            attempt_type="research_question",
            input_snapshot={"research_question_id": answered.id},
        )
        evidence_set = await create_evidence_set(
            session,
            run_id=run["id"],
            created_from_attempt_id=child.id,
        )
        await add_evidence_items(
            session,
            evidence_set_id=evidence_set.id,
            items=[
                research_evidence(
                    research_need_id="need-1",
                    source_type="legal_source",
                    status="found",
                    title="Avtalslagen",
                    excerpt="36 § avtalslagen",
                    locator="36 §",
                    source_url="https://example.test/avtalslagen",
                    provider="lagen.nu",
                )
            ],
        )
        await claim_freeze_evidence_set(session, evidence_set.id)
        await attach_evidence_set(
            session,
            attempt_id=child.id,
            evidence_set_id=evidence_set.id,
        )
        await mark_ready(session, child.id)
        answered.execution_attempt_id = child.id
        answered.status = "completed"
        await session.commit()

    response = await client.get(f"/execution/attempts/{parent.id}/research-overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"] == {
        "total": 2,
        "answered": 1,
        "running": 0,
        "waiting": 0,
        "insufficient": 0,
        "unanswered": 0,
        "failed": 0,
        "blocked": 1,
    }
    assert body["phase"] == "completed_with_gaps"
    answered_out = next(row for row in body["questions"] if row["id"] == answered.id)
    assert answered_out["status"] == "answered"
    assert answered_out["assigned_to"]["name"] == expert.name
    assert answered_out["sources"][0]["title"] == "Avtalslagen"
    waiting_out = next(row for row in body["questions"] if row["id"] == waiting.id)
    assert waiting_out["dependency_ids"] == [answered.id]
