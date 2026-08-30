"""Integration test: dd_panel run publishes live watch events."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

from app.llm import set_text_completer
from app.realtime.panel_broadcast import panel_broadcast
from app.services import jobs as jobs_service


@pytest.fixture
def mock_dd_panel_llm():
    score_counter = {"n": 0}

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "ENDAST JA eller NEJ" in user or "ONLY YES or NO" in user:
            return "JA"
        if "Ingen av experterna" in user or "None of the experts" in user:
            return "Panelen saknar rätt kompetens för frågan."
        if "ENDAST med JSON" in user or "ONLY with JSON" in user:
            score_counter["n"] += 1
            score = 5 + (score_counter["n"] % 4)
            return json.dumps({"score": score, "motivation": f"Bedömning {score_counter['n']}"})
        if "Poängtabell" in user or "Score table" in user:
            return "Sammanfattning: blandad bild med tydlig dissensus kring legal risk."
        if "Nuvarande delfråga" in user or "Current sub-question" in user:
            return "Vi går vidare till nästa delfråga."
        if "Öppna panelen" in user or "Open briefly" in user:
            return "Välkommen till DD-panelen."
        return "OK"

    set_text_completer(_complete)
    yield
    set_text_completer(None)


@pytest.mark.asyncio
async def test_dd_panel_run_emits_live_turn_events(client: AsyncClient, mock_dd_panel_llm, monkeypatch):
    monkeypatch.setattr(
        "app.services.dd.source_attribution.search_duckduckgo",
        lambda query, number_of_result_pages=5: [],
    )

    events: list[dict] = []
    original_publish = panel_broadcast.publish

    async def capture_publish(session_id: str, event: dict) -> None:
        events.append(event)
        await original_publish(session_id, event)

    monkeypatch.setattr(panel_broadcast, "publish", capture_publish)

    create = await client.post(
        "/dd/campaigns",
        json={"title": "Live DD", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
    )
    campaign_id = create.json()["id"]
    await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    candidate_id = (await client.get(f"/dd/campaigns/{campaign_id}")).json()["candidates"][0]["id"]

    session_resp = await client.post(
        f"/dd/campaigns/{campaign_id}/panel-sessions",
        json={"campaign_id": campaign_id, "candidate_id": candidate_id},
    )
    session_id = session_resp.json()["id"]

    done = asyncio.Event()

    def _schedule(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule)
    await client.post(f"/panel/sessions/{session_id}/run")
    await asyncio.wait_for(done.wait(), timeout=15)
    jobs_service.set_schedule_hook(None)

    types = [event["type"] for event in events]
    assert "turn.started" in types
    assert "turn.completed" in types
    assert types.count("turn.completed") >= 5
    assert events[-1]["type"] == "panel.finished"
    assert events[-1]["status"] == "succeeded"
    assert all(event.get("session_id") == session_id for event in events if "session_id" in event)
