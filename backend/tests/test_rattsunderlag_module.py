from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.modules.registry import MODULE_REGISTRY, report_binding_for_mode
from app.services import jobs as jobs_service
from app.services.rattsunderlag import MODULE_ID, REPORT_MODE, SOURCE_TYPE
from app.services.rattsunderlag.schemas import SearchPlan
from app.llm import set_structured_completer, set_text_completer
from app.services.spindoctor_context import build_spindoctor_context


def test_rattsunderlag_manifest_has_shared_renderer_mode():
    module = MODULE_REGISTRY[MODULE_ID]
    assert module.components == frozenset()
    assert module.report_modes == frozenset({REPORT_MODE})
    assert module.report is not None
    assert SOURCE_TYPE in module.report.source_types
    binding = report_binding_for_mode(REPORT_MODE)
    assert binding is module.report
    assert module.prompt_defaults_provider is not None
    assert module.spindoctor is not None


@pytest.mark.asyncio
async def test_research_job_writes_underlag_visible_without_module_filter(
    user_client: AsyncClient,
):
    async def planner(_messages, response_model):
        if response_model is SearchPlan:
            return SearchPlan(queries=["upphandling"])
        raise RuntimeError(f"Unexpected structured model {response_model}")

    async def summarizer(_messages):
        return "Likabehandling krävs. [[ref:2016:1145]]"

    set_structured_completer(planner)
    set_text_completer(summarizer)

    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await user_client.post(
            "/rattsunderlag/research",
            json={"fraga": "Måste en myndighet behandla anbudsgivare lika?"},
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["id"]
        await jobs_service._run_job(job_id)
        fetched = await user_client.get(f"/rattsunderlag/research/{job_id}")
        assert fetched.status_code == 200, fetched.text
        body = fetched.json()
        assert body["status"] == "succeeded", body.get("error")
        assert body["result"]["result"]["sourcing_status"] in {
            "complete",
            "partial",
        }
        underlag_id = body["result"]["underlag_id"]
        report_id = body["result"]["report_id"]

        scoped = await user_client.get("/underlag", params={"module": "rattsunderlag"})
        assert scoped.status_code == 200
        assert underlag_id in [row["id"] for row in scoped.json()["files"]]

        library = await user_client.get("/underlag")
        assert library.status_code == 200
        assert underlag_id in [row["id"] for row in library.json()["files"]]

        report = await user_client.get(f"/reports/{report_id}")
        assert report.status_code == 200
        assert report.json()["mode"] == REPORT_MODE
        html = await user_client.get(f"/reports/{report_id}/html")
        assert html.status_code == 200
        page = html.text
        assert "Tillämplig lagstiftning" in page
        assert "Praxis" in page
        assert "Förarbeten" in page
        assert "Bedömning" in page
        assert "[[ref:" not in page
        assert "[[ref:" not in body["result"]["result"]["sammanfattning"]
        listed = await user_client.get("/rattsunderlag/sessions")
        assert listed.status_code == 200
        sessions = listed.json()
        assert any(row["job_id"] == job_id for row in sessions)
        session_row = next(row for row in sessions if row["job_id"] == job_id)
        assert session_row["status"] == "succeeded"
        fetched_session = await user_client.get(f"/rattsunderlag/sessions/{session_row['id']}")
        assert fetched_session.status_code == 200
        assert fetched_session.json()["fraga"].startswith("Måste en myndighet")

        factory = jobs_service.job_session_factory()
        assert factory is not None
        async with factory() as db:
            _report, context = await build_spindoctor_context(db, report_id=report_id)
        assert "Likabehandling" in context
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_rattsunderlag_session_draft_then_run(user_client: AsyncClient):
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        created = await user_client.post(
            "/rattsunderlag/sessions",
            json={"fraga": "", "title": "Utkast"},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["id"]
        assert created.json()["status"] == "draft"

        patched = await user_client.patch(
            f"/rattsunderlag/sessions/{session_id}",
            json={"fraga": "Vad krävs för ogiltig upphandling?"},
        )
        assert patched.status_code == 200
        assert patched.json()["fraga"].startswith("Vad krävs")

        too_early = await user_client.post(f"/rattsunderlag/sessions/{session_id}/run")
        assert too_early.status_code == 202, too_early.text
        job_id = too_early.json()["job_id"]
        pending = await user_client.get(f"/rattsunderlag/sessions/{session_id}")
        assert pending.json()["status"] == "pending"
        assert pending.json()["job_id"] == job_id

        listed = await user_client.get("/rattsunderlag/sessions")
        assert any(row["id"] == session_id for row in listed.json())

        blocked = await user_client.delete(f"/rattsunderlag/sessions/{session_id}")
        assert blocked.status_code == 409
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_rattsunderlag_session_lookup_by_job_id(user_client: AsyncClient):
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await user_client.post(
            "/rattsunderlag/research",
            json={"fraga": "Får en myndighet diskriminera anbudsgivare?"},
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["id"]
        by_job = await user_client.get(f"/rattsunderlag/sessions/{job_id}")
        assert by_job.status_code == 200
        assert by_job.json()["job_id"] == job_id
    finally:
        jobs_service.set_schedule_hook(None)
