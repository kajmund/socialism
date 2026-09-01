"""Tests for panel engine generic_panel sessions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.llm import set_text_completer, set_tools_completer
from app.services import jobs as jobs_service
from app.services.panel.schemas import PanelSessionCreate, PanelSessionConfig, PanelExpertSlot


@pytest.fixture
def mock_panel_llm():
    counters = {"n": 0}
    seen_tools: list[list[str]] = []

    async def _complete(messages, *, model=None):
        counters["n"] += 1
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "JA"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return f"Anteckning {counters['n']}"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            return f"Inlägg {counters['n']}"
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Syntes: panelen enades om fortsatt DD."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen till panelen."
        return f"Svar {counters['n']}"

    async def _tools(messages, tools=None):
        if tools:
            seen_tools.append(
                [item["function"]["name"] for item in tools if item.get("function")]
            )
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)
    yield {"seen_tools": seen_tools}
    set_text_completer(None)
    set_tools_completer(None)


@pytest.mark.asyncio
async def test_panel_session_run_job(client: AsyncClient, mock_panel_llm):
    done = asyncio.Event()

    def _schedule(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule)

    create = await client.post(
        "/panel/sessions",
        json={
            "config": {
                "protocol": "generic_panel",
                "topic": "Förvärv av målbolag X",
                "brief": "Demo-session",
                "max_rounds": 1,
                "expert_slots": [
                    {"slot_id": "fin", "label": "Finansiell analytiker", "profile": "Siffror"},
                    {"slot_id": "legal", "label": "Jurist", "profile": "Avtal"},
                ],
            }
        },
    )
    assert create.status_code == 201
    session_id = create.json()["id"]

    run = await client.post(f"/panel/sessions/{session_id}/run")
    assert run.status_code == 202
    job_id = run.json()["job_id"]

    await asyncio.wait_for(done.wait(), timeout=10)

    job = await client.get(f"/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["status"] == "succeeded"

    session = await client.get(f"/panel/sessions/{session_id}")
    assert session.status_code == 200
    body = session.json()
    assert body["status"] == "succeeded"
    assert body["analysis"]
    factory = jobs_service.job_session_factory()
    assert factory is not None
    async with factory() as db:
        from app.services.panel.sessions import get_panel_session

        row = await get_panel_session(db, session_id)
        assert row is not None
        assert row.result is not None
        assert row.result["protocol"] == "generic_panel"
        assert row.result["summary"] == body["analysis"]
        assert row.result["claims"] == []
    assert len(body["transcript"]) >= 4
    assert any(t["phase"] == "opening" for t in body["transcript"])
    assert any(t["phase"] == "expert" for t in body["transcript"])
    assert mock_panel_llm["seen_tools"]
    offered = mock_panel_llm["seen_tools"][0]
    assert "search_companies" in offered
    assert "search_duckduckgo" in offered
    assert "search_wiki" in offered

    jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_panel_session_config_validation():
    cfg = PanelSessionConfig(
        topic="Test",
        expert_slots=[PanelExpertSlot(slot_id="a", label="Expert A")],
    )
    assert cfg.protocol == "generic_panel"
    assert PanelSessionCreate(config=cfg).config.max_rounds == 2
