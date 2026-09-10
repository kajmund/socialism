"""HTTP API: ExecutionRun → research → generic_panel → persisted result."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.database.models import EvidenceSet, ExecutionAttemptResult, PanelSession
from app.llm import set_structured_completer, set_text_completer, set_tools_completer
from app.services.execution import fail_attempt, get_attempt, mark_ready
from app.services.panel.research import empty_research_structured
from app.services.panel.synthesis import GenericPanelSynthesis, SynthesizedClaim
from app.services.research.composition import (
    ResearchCompositionError,
    build_standard_research_router,
    set_research_router_factory,
)
from app.services.research.models import ResearchContext, ResearchNeed, research_evidence
from app.services.research.registry import ResearchSourceRegistry
from app.services.research.router import ResearchRouter
from tests.conftest import TEST_CUSTOMER_ID

PANEL_CONFIG = {
    "topic": "Vad gäller skattesatsen?",
    "brief": "Kommunal skattesats.",
    "max_rounds": 1,
    "expert_slots": [
        {"slot_id": "legal", "label": "Jurist", "profile": "Skatt"},
    ],
}

RESEARCH_PLAN = {
    "needs": [
        {
            "id": "research_1",
            "question": "Vad är skattesatsen?",
            "why_needed": "behövs för bedömning",
            "requested_by": ["legal"],
            "source_types": ["customer_knowledge"],
        },
        {
            "id": "research_2",
            "question": "Finns jämförelse?",
            "why_needed": "behövs för bedömning",
            "requested_by": ["legal"],
            "source_types": ["case_knowledge"],
        },
    ]
}


class ScriptedSource:
    def __init__(self, source_type: str, *, mode: str) -> None:
        self.source_type = source_type
        self.provider_id = "fake"
        self.mode = mode
        self.calls = 0
        self.contexts: list[ResearchContext] = []

    async def research(self, need: ResearchNeed, context: ResearchContext):
        self.calls += 1
        self.contexts.append(context)
        if self.mode == "found":
            return [
                research_evidence(
                    research_need_id=need.id,
                    source_type=self.source_type,  # type: ignore[arg-type]
                    status="found",
                    title="Kommunens skattesats",
                    excerpt="skattesats 32%",
                    locator="p. 14",
                    source_id="doc-brief",
                    source_url="https://example.test/brief.pdf",
                    provider="fake",
                    score=0.91,
                    retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
                    metadata={"document_id": "doc-brief", "version": "3"},
                )
            ]
        if self.mode == "empty":
            return []
        raise RuntimeError("source exploded")


@pytest.fixture
def research_sources():
    found = ScriptedSource("customer_knowledge", mode="found")
    missing = ScriptedSource("case_knowledge", mode="empty")
    registry = ResearchSourceRegistry()
    registry.register(found)
    registry.register(missing)
    router = ResearchRouter(registry)
    set_research_router_factory(lambda _session: router)
    yield found, missing, router
    set_research_router_factory(None)


@pytest.fixture
def panel_llm():
    captured: list[list[dict]] = []

    async def _complete(messages, *, model=None):
        captured.append([dict(item) for item in messages])
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "JA"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return "Pad"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            return "Skattesatsen är 32% enligt [E1]."
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Fri analys med [E1]."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen."
        return "Svar"

    async def _tools(messages, tools=None):
        raise AssertionError("frozen-evidence execute must not use tool completions")

    async def _structured(messages, response_model):
        captured.append([dict(item) for item in messages])
        if response_model is GenericPanelSynthesis:
            return GenericPanelSynthesis(
                summary="Skattesatsen är 32%.",
                claims=[
                    SynthesizedClaim(
                        claim="Kommunalskatten är 32%.",
                        evidence="Fryst underlag [E1].",
                        judgment="Bedömd slutsats.",
                        evidence_refs=["E1"],
                    )
                ],
                unanswered=["Ingen jämförelse hittades."],
            )
        empty = empty_research_structured(response_model)
        if empty is not None:
            raise AssertionError("research-plan models must not run on execute")
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(_complete)
    set_tools_completer(_tools)
    set_structured_completer(_structured)
    yield captured
    set_text_completer(None)
    set_tools_completer(None)
    set_structured_completer(None)


async def _create_run(client: AsyncClient, **overrides) -> dict:
    payload = {
        "customer_id": TEST_CUSTOMER_ID,
        "module": "dd",
        "title": "Skattesats",
        "context": {"case_id": "case-1"},
    }
    payload.update(overrides)
    response = await client.post("/execution/runs", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _create_attempt(
    client: AsyncClient,
    run_id: str,
    *,
    attempt_type: str = "generic_panel",
    config: dict | None = None,
) -> dict:
    response = await client.post(
        f"/execution/runs/{run_id}/attempts",
        json={
            "attempt_type": attempt_type,
            "configuration_snapshot": config or dict(PANEL_CONFIG),
            "input_snapshot": {"topic": "Vad gäller skattesatsen?"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_create_run_and_attempt_are_created(client: AsyncClient):
    run = await _create_run(client)
    assert run["customer_id"] == TEST_CUSTOMER_ID
    assert run["module"] == "dd"
    assert run["title"] == "Skattesats"
    assert run["context"]["case_id"] == "case-1"
    assert run["created_at"]
    assert run["updated_at"]

    fetched = await client.get(f"/execution/runs/{run['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == run["id"]

    attempt = await _create_attempt(client, run["id"])
    assert attempt["status"] == "created"
    assert attempt["attempt_type"] == "generic_panel"
    assert attempt["run_id"] == run["id"]
    assert attempt["parent_attempt_id"] is None
    assert attempt["research_plan_snapshot"] is None
    assert attempt["evidence"] is None
    assert attempt["result"] is None
    assert attempt["configuration_snapshot"]["topic"] == PANEL_CONFIG["topic"]

    detail = await client.get(f"/execution/attempts/{attempt['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "created"

    listed = await client.get(f"/execution/runs/{run['id']}/attempts")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [attempt["id"]]

    second = await _create_attempt(client, run["id"])
    listed = await client.get(f"/execution/runs/{run['id']}/attempts")
    assert {row["id"] for row in listed.json()} == {attempt["id"], second["id"]}
    assert all(row["evidence"] is None for row in listed.json())


@pytest.mark.asyncio
async def test_research_then_evidence_is_frozen_and_ordered(
    client: AsyncClient, research_sources
):
    found, missing, _router = research_sources
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])

    researched = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert researched.status_code == 200, researched.text
    body = researched.json()
    assert body["status"] == "ready"
    assert body["found_count"] == 1
    assert body["not_found_count"] == 1
    assert body["error_count"] == 0
    assert body["evidence_set_id"]
    assert found.calls == 1
    assert missing.calls == 1
    assert found.contexts[0].scope.customer_id == TEST_CUSTOMER_ID
    assert found.contexts[0].scope.case_id == "case-1"

    detail = await client.get(f"/execution/attempts/{attempt['id']}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["status"] == "ready"
    assert detail_body["research_plan_snapshot"]["needs"][0]["id"] == "research_1"
    assert detail_body["evidence"]["status"] == "frozen"
    assert detail_body["evidence"]["found_count"] == 1
    assert detail_body["evidence"]["not_found_count"] == 1

    evidence = await client.get(f"/execution/attempts/{attempt['id']}/evidence")
    assert evidence.status_code == 200
    set_body = evidence.json()
    assert set_body["status"] == "frozen"
    assert [item["ordinal"] for item in set_body["items"]] == [0, 1]
    assert [item["status"] for item in set_body["items"]] == ["found", "not_found"]
    first = set_body["items"][0]
    assert first["excerpt"] == "skattesats 32%"
    assert first["locator"] == "p. 14"
    assert first["original_evidence_id"]
    assert first["content_hash"]
    assert first["provenance"]
    assert first["retrieved_at"]


@pytest.mark.asyncio
async def test_ready_execute_returns_persisted_panel_result(
    client_db, research_sources, panel_llm
):
    client, factory = client_db
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    researched = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert researched.json()["status"] == "ready"
    evidence_set_id = researched.json()["evidence_set_id"]

    executed = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert executed.status_code == 200, executed.text
    payload = executed.json()
    assert payload["attempt"]["status"] == "completed"
    assert payload["attempt"]["evidence"]["evidence_set_id"] == evidence_set_id
    result = payload["result"]
    assert result is not None
    assert result["result_type"] == "generic_panel"
    assert result["payload"]["protocol"] == "generic_panel"
    assert result["payload"]["summary"]
    assert result["evidence_refs"]["E1"]["ordinal"] == 0
    assert result["panel_session_id"]

    fetched = await client.get(f"/execution/attempts/{attempt['id']}/result")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == result["id"]
    assert fetched.json()["payload"] == result["payload"]

    detail = await client.get(f"/execution/attempts/{attempt['id']}")
    assert detail.json()["result"]["id"] == result["id"]
    assert detail.json()["status"] == "completed"

    blob = "\n".join(item["content"] for batch in panel_llm for item in batch)
    assert "[E1]" in blob
    assert "skattesats 32%" in blob

    async with factory() as session:
        sessions = (await session.execute(select(func.count()).select_from(PanelSession))).scalar()
        results = (
            await session.execute(select(func.count()).select_from(ExecutionAttemptResult))
        ).scalar()
        sets = (await session.execute(select(func.count()).select_from(EvidenceSet))).scalar()
    assert sessions == 1
    assert results == 1
    assert sets == 1


@pytest.mark.asyncio
async def test_second_execute_is_idempotent(client_db, research_sources, panel_llm):
    client, factory = client_db
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    first = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert first.status_code == 200
    first_id = first.json()["result"]["id"]
    first_session = first.json()["result"]["panel_session_id"]

    second = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert second.status_code == 200
    assert second.json()["result"]["id"] == first_id
    assert second.json()["result"]["panel_session_id"] == first_session

    async with factory() as session:
        sessions = (await session.execute(select(func.count()).select_from(PanelSession))).scalar()
        results = (
            await session.execute(select(func.count()).select_from(ExecutionAttemptResult))
        ).scalar()
        sets = (await session.execute(select(func.count()).select_from(EvidenceSet))).scalar()
    assert sessions == 1
    assert results == 1
    assert sets == 1


@pytest.mark.asyncio
async def test_completed_execute_skips_prompts_when_dependency_is_gone(
    client: AsyncClient, research_sources, panel_llm, monkeypatch
):
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    first = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["attempt"]["status"] == "completed"
    first_result_id = first_body["result"]["id"]

    async def _boom_prompts(*_args, **_kwargs):
        raise AssertionError("prompts must not load for a completed Attempt")

    monkeypatch.setattr("app.api.execution.require_active_prompts", _boom_prompts)
    monkeypatch.setattr(
        "app.api.execution.execute_registered_attempt",
        _boom_prompts,
    )
    second = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert second.status_code == 200
    assert second.json()["result"]["id"] == first_result_id
    assert second.json()["attempt"]["status"] == "completed"


@pytest.mark.asyncio
async def test_second_research_is_idempotent(client: AsyncClient, research_sources):
    found, missing, _router = research_sources
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    first = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert first.status_code == 200
    evidence_id = first.json()["evidence_set_id"]
    calls = found.calls + missing.calls

    second = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert second.status_code == 200
    assert second.json()["evidence_set_id"] == evidence_id
    assert second.json()["status"] == "ready"
    assert found.calls + missing.calls == calls


@pytest.mark.asyncio
async def test_ready_research_skips_router_when_dependency_is_gone(
    client: AsyncClient, research_sources
):
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    first = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert first.status_code == 200
    first_body = first.json()

    def _boom(_session):
        raise AssertionError("ResearchRouter must not be built for a ready Attempt")

    set_research_router_factory(_boom)
    try:
        second = await client.post(
            f"/execution/attempts/{attempt['id']}/research",
            json={"research_plan": RESEARCH_PLAN},
        )
        assert second.status_code == 200
        assert second.json() == first_body
    finally:
        set_research_router_factory(None)


@pytest.mark.asyncio
async def test_ready_research_fast_path_still_enforces_scope(
    client: AsyncClient, research_sources, admin_token: str, bolag_token: str
):
    client.headers["Authorization"] = f"Bearer {admin_token}"
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    first = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert first.status_code == 200
    client.headers["Authorization"] = f"Bearer {bolag_token}"
    forbidden = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_execute_on_created_is_conflict(client: AsyncClient):
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    response = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_execute_without_frozen_evidence_is_conflict(client_db):
    client, factory = client_db
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    async with factory() as session:
        await mark_ready(session, attempt["id"])
        await session.commit()
    response = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_failed_attempt_rejects_research_and_execute(client_db, research_sources):
    client, factory = client_db
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    async with factory() as session:
        await fail_attempt(session, attempt["id"])
        await session.commit()

    research = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert research.status_code == 409
    execute = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert execute.status_code == 409


@pytest.mark.asyncio
async def test_source_error_still_ready_and_visible(client: AsyncClient):
    exploding = ScriptedSource("customer_knowledge", mode="error")
    registry = ResearchSourceRegistry()
    registry.register(exploding)
    set_research_router_factory(lambda _session: ResearchRouter(registry))
    try:
        run = await _create_run(client)
        attempt = await _create_attempt(client, run["id"])
        researched = await client.post(
            f"/execution/attempts/{attempt['id']}/research",
            json={
                "research_plan": {
                    "needs": [
                        {
                            "id": "research_1",
                            "question": "Vad är skattesatsen?",
                            "why_needed": "behövs",
                            "requested_by": ["legal"],
                            "source_types": ["customer_knowledge"],
                        }
                    ]
                }
            },
        )
        assert researched.status_code == 200
        assert researched.json()["status"] == "ready"
        assert researched.json()["error_count"] == 1
        evidence = await client.get(f"/execution/attempts/{attempt['id']}/evidence")
        assert evidence.json()["items"][0]["status"] == "error"
    finally:
        set_research_router_factory(None)


@pytest.mark.asyncio
async def test_unsupported_attempt_type_rejected(client_db, research_sources):
    client, _factory = client_db
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"], attempt_type="word_review")
    researched = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert researched.status_code == 200
    response = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert response.status_code == 422
    assert "word_review" in response.json()["detail"]


@pytest.mark.asyncio
async def test_duplicate_need_ids_are_unprocessable(client: AsyncClient, research_sources):
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    response = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={
            "research_plan": {
                "needs": [
                    {
                        "id": "dup",
                        "question": "En?",
                        "why_needed": "x",
                        "source_types": ["customer_knowledge"],
                    },
                    {
                        "id": "dup",
                        "question": "Två?",
                        "why_needed": "x",
                        "source_types": ["customer_knowledge"],
                    },
                ]
            }
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_research_and_execute_reject_customer_id_override(client: AsyncClient):
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    research = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN, "customer_id": 999},
    )
    assert research.status_code == 422
    execute = await client.post(
        f"/execution/attempts/{attempt['id']}/execute",
        json={"customer_id": 999},
    )
    assert execute.status_code == 422


@pytest.mark.asyncio
async def test_cross_customer_access_is_forbidden(
    client: AsyncClient, admin_token: str, bolag_token: str
):
    client.headers["Authorization"] = f"Bearer {admin_token}"
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    client.headers["Authorization"] = f"Bearer {bolag_token}"
    forbidden = await client.get(f"/execution/attempts/{attempt['id']}")
    assert forbidden.status_code == 403
    evidence = await client.get(f"/execution/attempts/{attempt['id']}/evidence")
    assert evidence.status_code == 403
    result = await client.get(f"/execution/attempts/{attempt['id']}/result")
    assert result.status_code == 403
    research = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert research.status_code == 403
    execute = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert execute.status_code == 403


@pytest.mark.asyncio
async def test_invalid_generic_panel_snapshot_is_rejected(client: AsyncClient):
    run = await _create_run(client)
    response = await client.post(
        f"/execution/runs/{run['id']}/attempts",
        json={
            "attempt_type": "generic_panel",
            "configuration_snapshot": {
                "topic": "Vad gäller skattesatsen?",
                "max_rounds": 0,
                "expert_slots": [
                    {"slot_id": "legal", "label": "Jurist", "profile": "Skatt"},
                ],
            },
            "input_snapshot": {"topic": "Vad gäller skattesatsen?"},
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_research_fails_closed_without_vector_store(client: AsyncClient):
    set_research_router_factory(None)
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    response = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert response.status_code == 500
    assert "KnowledgeVectorStore" in response.json()["detail"]
    detail = await client.get(f"/execution/attempts/{attempt['id']}")
    assert detail.json()["status"] == "created"


def test_standard_research_router_refuses_empty_memory_store():
    set_research_router_factory(None)
    with pytest.raises(ResearchCompositionError, match="KnowledgeVectorStore"):
        build_standard_research_router(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_empty_run_title_is_bad_request(client: AsyncClient):
    response = await client.post(
        "/execution/runs",
        json={
            "customer_id": TEST_CUSTOMER_ID,
            "module": "dd",
            "title": "   ",
            "context": {},
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_missing_entities_are_not_found(client: AsyncClient):
    assert (await client.get("/execution/runs/missing")).status_code == 404
    assert (await client.get("/execution/attempts/missing")).status_code == 404
    assert (await client.get("/execution/attempts/missing/evidence")).status_code == 404
    assert (await client.get("/execution/attempts/missing/result")).status_code == 404
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    assert (await client.get(f"/execution/attempts/{attempt['id']}/evidence")).status_code == 404
    assert (await client.get(f"/execution/attempts/{attempt['id']}/result")).status_code == 404


@pytest.mark.asyncio
async def test_execute_does_not_run_research_router(
    client: AsyncClient, research_sources, panel_llm
):
    found, missing, _router = research_sources
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    calls_after_research = found.calls + missing.calls
    executed = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert executed.status_code == 200
    assert found.calls + missing.calls == calls_after_research


@pytest.mark.asyncio
async def test_research_in_progress_is_conflict(client_db, research_sources):
    client, factory = client_db
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    async with factory() as session:
        row = await get_attempt(session, attempt["id"])
        row.status = "researching"
        await session.commit()
    response = await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_execute_in_progress_is_conflict(client_db, research_sources):
    client, factory = client_db
    run = await _create_run(client)
    attempt = await _create_attempt(client, run["id"])
    await client.post(
        f"/execution/attempts/{attempt['id']}/research",
        json={"research_plan": RESEARCH_PLAN},
    )
    async with factory() as session:
        row = await get_attempt(session, attempt["id"])
        row.status = "running"
        await session.commit()
    response = await client.post(f"/execution/attempts/{attempt['id']}/execute")
    assert response.status_code == 409
