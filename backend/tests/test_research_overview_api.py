from __future__ import annotations

from uuid import uuid4

from sqlalchemy import event, select

from app.api.execution import _domain_result_analysis
from app.database.models import Persona, ResearchNeedExecution, ResearchRuntimeNeed
from app.services.execution import (
    add_evidence_items,
    attach_evidence_set,
    claim_freeze_evidence_set,
    create_attempt,
    create_evidence_set,
    mark_ready,
    persist_research_assessment,
)
from app.services.research.assessment import ResearchAssessmentDraft, ResearchNeedAssessment
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
                runtime_need_id="need-1",
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
                ),
                *[
                    research_evidence(
                        research_need_id="need-1",
                        source_type="legal_source",
                        status="found",
                        title=f"Relevant {index}",
                        excerpt=f"Relevant excerpt {index}",
                        source_url=f"https://example.test/relevant/{index}",
                        provider="lagen.nu",
                    )
                    for index in range(7)
                ],
                *[
                    research_evidence(
                        research_need_id="need-2",
                        source_type="legal_source",
                        status="error",
                        title=f"Unrelated {index}",
                        excerpt=f"Unrelated excerpt {index}",
                        source_id=f"https://example.test/unrelated/{index}",
                        source_url=f"https://example.test/unrelated/{index}",
                        provider="lagen.nu",
                    )
                    for index in range(70)
                ],
            ],
        )
        await claim_freeze_evidence_set(session, evidence_set.id)
        await attach_evidence_set(
            session,
            attempt_id=child.id,
            evidence_set_id=evidence_set.id,
        )
        await mark_ready(session, child.id)
        await persist_research_assessment(
            session,
            attempt_id=child.id,
            evidence_set_id=evidence_set.id,
            evidence_fingerprint="overview-fixture",
            draft=ResearchAssessmentDraft(
                result="insufficient",
                rationale="GLOBAL: need-2 has errors",
                need_assessments=[
                    ResearchNeedAssessment(
                        research_need_id="need-1",
                        sufficient=True,
                        supporting_evidence_ids=[],
                        missing_or_weak="Need-1 only",
                    )
                ],
            ),
        )
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
    assert answered_out["blocking_dependency_ids"] == []
    assert answered_out["assigned_to"]["name"] == expert.name
    assert answered_out["sources"][0]["title"] == "Avtalslagen"
    assert answered_out["source_count"] == 8
    assert len(answered_out["sources"]) == 8
    assert answered_out["need_assessment"]["missing_or_weak"] == "Need-1 only"
    assert "assessment_rationale" not in answered_out
    assert "completeness_rationale" not in answered_out
    evidence_response = await client.get(f"/execution/attempts/{child.id}/evidence")
    assert evidence_response.status_code == 200
    assert len(evidence_response.json()["items"]) == 78
    waiting_out = next(row for row in body["questions"] if row["id"] == waiting.id)
    assert waiting_out["dependency_ids"] == [answered.id]
    assert waiting_out["blocking_dependency_ids"] == []


async def test_overview_keeps_shared_raw_source_domain_results_with_their_needs(client_db):
    from app.database.models import RawSource
    from app.services.legal_research_result import (
        CaseLawAnalysis,
        LegalCitation,
        LegalQuestionRelation,
        LegalResearchResult,
        LegalSourceIdentity,
    )

    client, factory = client_db
    run = (
        await client.post(
            "/execution/runs",
            json={
                "customer_id": TEST_CUSTOMER_ID,
                "module": "expertgranskning",
                "title": "Gemensam källa",
                "context": {},
            },
        )
    ).json()
    uri = "https://lagen.nu/dom/nja/2005s142"
    raw = "HD prövade ansvarsbegränsningen. Villkoret jämkades."
    async with factory() as session:
        parent = await create_attempt(
            session,
            run_id=run["id"],
            attempt_type="generic_panel",
            configuration_snapshot={},
            input_snapshot={},
        )
        specific = await create_specific_question(
            session, run_id=run["id"], text="Klausul", context={}, origin_kind="expertgranskning"
        )
        questions = [
            await create_general_question(
                session,
                attempt_id=parent.id,
                specific_question_id=specific.id,
                draft=GeneralQuestionDraft(question=f"Fråga {need}", runtime_need_id=need),
            )
            for need in ("need-a", "need-b")
        ]
        child = await create_attempt(
            session,
            run_id=run["id"],
            parent_attempt_id=parent.id,
            attempt_type="research_question",
            input_snapshot={"research_question_id": questions[0].id},
        )
        evidence_set = await create_evidence_set(
            session, run_id=run["id"], created_from_attempt_id=child.id
        )
        source = LegalSourceIdentity(kind="case_law", title="NJA 2005 s. 142", canonical_uri=uri)
        items = []
        for need, excerpt, relation in (
            ("need-a", "HD prövade ansvarsbegränsningen.", "supports"),
            ("need-b", "Villkoret jämkades.", "limits"),
        ):
            legal = LegalResearchResult(
                source=source,
                relation=LegalQuestionRelation(
                    relation=relation, explanation=excerpt, confidence="high"
                ),
                case_law=CaseLawAnalysis(
                    legal_issue=need,
                    court_reasoning=excerpt,
                    outcome=excerpt,
                    citations=[LegalCitation(source_uri=uri, quote=excerpt)],
                ),
                raw_text=raw,
            )
            items.append(
                research_evidence(
                    research_need_id=need,
                    source_type="swedish_case_law",
                    status="found",
                    title="NJA 2005 s. 142",
                    excerpt=excerpt,
                    source_id=uri,
                    source_url=uri,
                    provider="lagen_nu",
                    legal_result=legal,
                )
            )
        await add_evidence_items(session, evidence_set_id=evidence_set.id, items=items)
        await claim_freeze_evidence_set(session, evidence_set.id)
        await attach_evidence_set(session, attempt_id=child.id, evidence_set_id=evidence_set.id)
        await mark_ready(session, child.id)
        for question in questions:
            question.execution_attempt_id = child.id
            question.status = "completed"
        assert len((await session.scalars(select(RawSource))).all()) == 1
        await session.commit()
        sync_engine = session.get_bind()
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        overview = (await client.get(f"/execution/attempts/{parent.id}/research-overview")).json()
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)
    sql = "\n".join(statements).lower()
    assert "raw_sources" not in sql
    assert "research_claims" not in sql
    assert "evidence_passages" not in sql
    by_need = {row["question"]: row for row in overview["questions"]}
    assert [row["source_count"] for row in by_need.values()] == [1, 1]
    assert by_need["Fråga need-a"]["sources"][0]["excerpt"] == "HD prövade ansvarsbegränsningen."
    assert by_need["Fråga need-b"]["sources"][0]["excerpt"] == "Villkoret jämkades."
    assert by_need["Fråga need-a"]["sources"][0]["analysis"] == "HD prövade ansvarsbegränsningen."
    assert by_need["Fråga need-b"]["sources"][0]["analysis"] == "Villkoret jämkades."
    assert (
        by_need["Fråga need-a"]["sources"][0]["id"] != by_need["Fråga need-b"]["sources"][0]["id"]
    )
    assert (
        by_need["Fråga need-a"]["sources"][0]["raw_source_id"]
        == by_need["Fråga need-b"]["sources"][0]["raw_source_id"]
    )
    assert (
        by_need["Fråga need-a"]["sources"][0]["domain_result_id"]
        != by_need["Fråga need-b"]["sources"][0]["domain_result_id"]
    )
    attempt_evidence = (await client.get(f"/execution/attempts/{child.id}/evidence")).json()
    assert len(attempt_evidence["items"]) == 2
    assert len(attempt_evidence["sources"]) == 1
    assert len(attempt_evidence["sources"][0]["domain_result_ids"]) == 2


def _runtime_need(attempt_id: str, need_id: str, question: str) -> ResearchRuntimeNeed:
    return ResearchRuntimeNeed(
        id=uuid4().hex,
        attempt_id=attempt_id,
        research_need_id=need_id,
        question=question,
        why_needed="Källan behövs för frågan.",
        requested_by=[],
        source_types=["legal_source"],
        domains=[],
        modalities=[],
        capabilities=[],
        origin="initial",
        wave_number=0,
        source_gap="",
        question_key=need_id,
    )


async def test_overview_shows_committed_needs_and_evidence_before_ready(client_db):
    client, factory = client_db
    run = (
        await client.post(
            "/execution/runs",
            json={
                "customer_id": TEST_CUSTOMER_ID,
                "module": "expertgranskning",
                "title": "Pågående research",
                "context": {},
            },
        )
    ).json()
    async with factory() as session:
        parent = await create_attempt(
            session,
            run_id=run["id"],
            attempt_type="generic_panel",
            configuration_snapshot={},
            input_snapshot={},
        )
        specific = await create_specific_question(
            session,
            run_id=run["id"],
            text="Vad innebär klausulen?",
            context={},
            origin_kind="expertgranskning",
        )
        question = await create_general_question(
            session,
            attempt_id=parent.id,
            specific_question_id=specific.id,
            draft=GeneralQuestionDraft(question="Hur tillämpas klausulen?"),
        )
        child = await create_attempt(
            session,
            run_id=run["id"],
            parent_attempt_id=parent.id,
            attempt_type="research_question",
            input_snapshot={"research_question_id": question.id},
        )
        question.execution_attempt_id = child.id
        question.status = "running"
        evidence_set = await create_evidence_set(
            session, run_id=run["id"], created_from_attempt_id=child.id
        )
        await add_evidence_items(
            session,
            evidence_set_id=evidence_set.id,
            items=[
                research_evidence(
                    research_need_id="research_3",
                    source_type="legal_source",
                    status="found",
                    title="Avtalslagen 36 §",
                    excerpt="Oskäligt avtalsvillkor",
                    source_url="https://lagen.nu/1915:218#P36",
                    provider="lagen.nu",
                )
            ],
        )
        await attach_evidence_set(session, attempt_id=child.id, evidence_set_id=evidence_set.id)
        session.add(_runtime_need(child.id, "research_3", "Vilka rekvisit gäller för 36 §?"))
        session.add(_runtime_need(child.id, "research_5", "Hur har SOU 1974:83 tolkats?"))
        session.add(
            ResearchNeedExecution(
                id=uuid4().hex,
                attempt_id=child.id,
                research_need_id="research_3",
                status="completed",
            )
        )
        session.add(
            ResearchNeedExecution(
                id=uuid4().hex,
                attempt_id=child.id,
                research_need_id="research_5",
                status="running",
            )
        )
        await session.commit()

    body = (await client.get(f"/execution/attempts/{parent.id}/research-overview")).json()
    by_question = {row["question"]: row for row in body["questions"]}
    assert body["phase"] == "researching"
    assert body["attempt_status"] != "ready"
    assert by_question["Vilka rekvisit gäller för 36 §?"]["source_count"] == 1
    assert by_question["Vilka rekvisit gäller för 36 §?"]["status"] == "answered"
    assert by_question["Hur har SOU 1974:83 tolkats?"]["status"] == "running"
    assert by_question["Hur har SOU 1974:83 tolkats?"]["source_count"] == 0


def test_domain_result_analysis_ignores_non_object_relation():
    assert _domain_result_analysis({"relation": {"explanation": "HD jämkade."}}) == "HD jämkade."
    assert _domain_result_analysis({"relation": "supports"}) is None
    assert _domain_result_analysis({"relation": {}}) is None
    assert _domain_result_analysis(None) is None
