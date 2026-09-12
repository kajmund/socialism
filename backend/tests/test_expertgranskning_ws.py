"""Live /ws/expertgranskning events from Word-review jobs."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.llm import set_structured_completer
from app.realtime.expertgranskning_broadcast import expertgranskning_broadcast
from app.services import jobs as jobs_service
from app.services.expertgranskning.schemas import (
    WordBatchModeration,
    WordCommentConvergence,
    WordExpertComment,
    WordExpertRaiseHand,
    WordHeadingAssessment,
    WordRewriteSuggestion,
)
from tests.test_expertgranskning_word_review import _moderation_for_batch
from tests.test_expertgranskning_word_review import (
    DEFAULT_EXPERT_LABELS,
    _create_expert_panel,
    _identity_label,
    _passthrough_comment_convergence,
    _review_task,
)


def _sections(text: str = "Detta stycke är tillräckligt långt för granskning.") -> list[dict]:
    return [
        {
            "heading": "Inledning",
            "heading_paragraph_index": 0,
            "paragraphs": [
                {
                    "index": 1,
                    "text": text,
                    "style": "Normal",
                }
            ],
        }
    ]


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
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text="", motivering="")
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            label = _identity_label(messages)
            if label == DEFAULT_EXPERT_LABELS[0]:
                return WordExpertRaiseHand(question_ids=["q1"])
            return WordExpertRaiseHand(question_ids=[])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="En live-kommentar.")
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
        raise AssertionError(f"unexpected model {response_model}")

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await client.post(
            "/expertgranskning/word-jobs",
            json={"task": _review_task(panel_id), "sections": _sections()},
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        await jobs_service._run_job(job_id)

        types = [event["type"] for event in events]
        assert types.count("expertgranskning.action.created") == 2
        assert types.count("expertgranskning.progress") == 1
        progress = next(
            event for event in events if event["type"] == "expertgranskning.progress"
        )
        assert progress["sections_completed"] == 1
        assert progress["sections_total"] == 1
        assert progress["actions_created"] == 2
        assert types[-1] == "expertgranskning.finished"
        assert events[-1]["status"] == "succeeded"
        assert events[-1]["job_id"] == job_id
        assert events[0]["action"]["content"] == "Finansiell analytiker: En live-kommentar."
        assert events[0]["action"]["action_type"] == "comment"
        assert events[1]["action"]["action_type"] == "comment"
        assert events[1]["action"]["content"] == "Tydligare rubrik"
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
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            label = _identity_label(messages)
            if label == DEFAULT_EXPERT_LABELS[0]:
                return WordExpertRaiseHand(question_ids=["q1"])
            return WordExpertRaiseHand(question_ids=[])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Sparad innan kraschen.")
        raise RuntimeError("heading boom")

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await client.post(
            "/expertgranskning/word-jobs",
            json={"task": _review_task(panel_id), "sections": _sections()},
        )
        assert started.status_code == 202, started.text
        await jobs_service._run_job(started.json()["job_id"])
        types = [event["type"] for event in events]
        assert "expertgranskning.action.created" not in types
        assert "expertgranskning.progress" not in types
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
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text="", motivering="")
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            label = _identity_label(messages)
            if label == DEFAULT_EXPERT_LABELS[0]:
                return WordExpertRaiseHand(question_ids=["q1"])
            return WordExpertRaiseHand(question_ids=[])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Kommentar att fästa live.")
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
        raise AssertionError(f"unexpected model {response_model}")

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await client.post(
            "/expertgranskning/word-jobs",
            json={
                "task": _review_task(panel_id),
                "sections": _sections(
                    "Detta stycke är tillräckligt långt för en kommentar."
                ),
            },
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        await jobs_service._run_job(job_id)
        listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
        assert listed.status_code == 200
        rows = listed.json()
        assert len(rows) == 1
        claimed = await client.post(
            f"/expertgranskning/word-jobs/{job_id}/actions/{rows[0]['id']}/claim",
            json={"application_id": "app-ws"},
        )
        assert claimed.status_code == 200, claimed.text
        completed = await client.post(
            f"/expertgranskning/word-jobs/{job_id}/actions/{rows[0]['id']}/complete",
            json={"application_id": "app-ws", "word_artifact_id": "word-comment-ws"},
        )
        assert completed.status_code == 200, completed.text
        updated = [
            event
            for event in events
            if event["type"] == "expertgranskning.action.updated"
        ]
        assert len(updated) == 2
        assert updated[-1]["job_id"] == job_id
        assert updated[-1]["action"]["word_artifact_id"] == "word-comment-ws"
        assert updated[-1]["action"]["status"] == "applied"
    finally:
        jobs_service.set_schedule_hook(None)
