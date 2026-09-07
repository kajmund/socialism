"""Live /ws/expertgranskning events from Word-review jobs."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.llm import set_structured_completer
from app.realtime.expertgranskning_broadcast import expertgranskning_broadcast
from app.services import jobs as jobs_service
from app.services.expertgranskning.schemas import (
    WordHeadingAssessment,
    WordParagraphComment,
    WordParagraphComments,
)
from tests.test_expertgranskning_word_review import (
    _create_expert_panel,
    _first_slot_id,
)


@pytest.mark.asyncio
async def test_word_review_emits_result_created_then_finished(
    client: AsyncClient, monkeypatch
):
    events: list[dict] = []
    original = expertgranskning_broadcast.publish

    async def capture(job_id: str, event: dict) -> None:
        events.append(event)
        await original(job_id, event)

    monkeypatch.setattr(expertgranskning_broadcast, "publish", capture)

    async def completer(messages, response_model):
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag="Tydligare rubrik")
        return WordParagraphComments(
            comments=[
                WordParagraphComment(
                    expert_id=_first_slot_id(messages[-1]["content"]),
                    expert_namn="ignored",
                    kommentar="En live-kommentar.",
                )
            ]
        )

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await client.post(
            "/expertgranskning/word-jobs",
            json={
                "panel_id": panel_id,
                "sections": [
                    {
                        "heading": "Inledning",
                        "heading_paragraph_index": 0,
                        "paragraphs": [
                            {
                                "index": 1,
                                "text": "Detta stycke är tillräckligt långt för granskning.",
                                "style": "Normal",
                            }
                        ],
                    }
                ],
            },
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        await jobs_service._run_job(job_id)

        types = [event["type"] for event in events]
        assert types.count("expertgranskning.result.created") == 2
        assert types[-1] == "expertgranskning.finished"
        assert events[-1]["status"] == "succeeded"
        assert events[-1]["job_id"] == job_id
        assert events[0]["result"]["kommentar"] == "En live-kommentar."
        assert events[0]["result"]["is_heading_suggestion"] is False
        assert events[1]["result"]["is_heading_suggestion"] is True
        assert events[1]["result"]["kommentar"] == "Tydligare rubrik"
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_word_review_emits_finished_on_failure(client: AsyncClient, monkeypatch):
    events: list[dict] = []
    original = expertgranskning_broadcast.publish

    async def capture(job_id: str, event: dict) -> None:
        events.append(event)
        await original(job_id, event)

    monkeypatch.setattr(expertgranskning_broadcast, "publish", capture)

    async def completer(messages, response_model):
        if response_model is WordParagraphComments:
            return WordParagraphComments(
                comments=[
                    WordParagraphComment(
                        expert_id=_first_slot_id(messages[-1]["content"]),
                        expert_namn="ignored",
                        kommentar="Sparad innan kraschen.",
                    )
                ]
            )
        raise RuntimeError("heading boom")

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await client.post(
            "/expertgranskning/word-jobs",
            json={
                "panel_id": panel_id,
                "sections": [
                    {
                        "heading": "Inledning",
                        "heading_paragraph_index": 0,
                        "paragraphs": [
                            {
                                "index": 1,
                                "text": "Detta stycke är tillräckligt långt för granskning.",
                                "style": "Normal",
                            }
                        ],
                    }
                ],
            },
        )
        assert started.status_code == 202, started.text
        await jobs_service._run_job(started.json()["job_id"])
        types = [event["type"] for event in events]
        assert "expertgranskning.result.created" in types
        assert types[-1] == "expertgranskning.finished"
        assert events[-1]["status"] == "failed"
        assert "heading boom" in (events[-1].get("error") or "")
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_word_result_patch_emits_updated(client: AsyncClient, monkeypatch):
    events: list[dict] = []
    original = expertgranskning_broadcast.publish

    async def capture(job_id: str, event: dict) -> None:
        events.append(event)
        await original(job_id, event)

    monkeypatch.setattr(expertgranskning_broadcast, "publish", capture)

    async def completer(messages, response_model):
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        return WordParagraphComments(
            comments=[
                WordParagraphComment(
                    expert_id=_first_slot_id(messages[-1]["content"]),
                    expert_namn="ignored",
                    kommentar="Kommentar att fästa live.",
                )
            ]
        )

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await client.post(
            "/expertgranskning/word-jobs",
            json={
                "panel_id": panel_id,
                "sections": [
                    {
                        "heading": "Inledning",
                        "heading_paragraph_index": 0,
                        "paragraphs": [
                            {
                                "index": 1,
                                "text": "Detta stycke är tillräckligt långt för en kommentar.",
                                "style": "Normal",
                            }
                        ],
                    }
                ],
            },
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        await jobs_service._run_job(job_id)
        listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/results")
        assert listed.status_code == 200
        rows = listed.json()
        assert len(rows) == 1
        patched = await client.patch(
            f"/expertgranskning/word-jobs/{job_id}/results/{rows[0]['id']}",
            json={"comment_id": "word-comment-ws"},
        )
        assert patched.status_code == 200, patched.text
        updated = [event for event in events if event["type"] == "expertgranskning.result.updated"]
        assert len(updated) == 1
        assert updated[0]["job_id"] == job_id
        assert updated[0]["result"]["comment_id"] == "word-comment-ws"
        assert updated[0]["result"]["status"] == "posted"
    finally:
        jobs_service.set_schedule_hook(None)
