"""Word paragraph review: sequential method, jobs table, incremental results."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database.models import ExpertgranskningResult, Job, PanelSession
from app.llm import set_structured_completer
from app.services import jobs as jobs_service
from app.services.expertgranskning import WORD_JOB_KIND, WORD_REVIEW_METHOD
from app.services.expertgranskning.schemas import (
    WordHeadingAssessment,
    WordParagraphComment,
    WordParagraphComments,
)
from app.services.expertgranskning.word_review import (
    is_heading_1_to_3,
    paragraph_word_count,
    should_review_paragraph,
    word_paragraph_review,
)
from app.services.kund_store import BOLAG_DEMO_KUND_SLUG
from app.services.panel.methods import DELIBERATION_METHODS
from tests.conftest import BOLAG_USER_ID, mint_access_token


def test_filter_skips_short_and_heading_styles():
    from app.services.expertgranskning.schemas import WordDocumentParagraph

    assert paragraph_word_count("en två tre") == 3
    assert paragraph_word_count("en två tre fyra") == 4
    assert is_heading_1_to_3("Heading 1")
    assert is_heading_1_to_3("heading 2")
    assert is_heading_1_to_3("Rubrik 3")
    assert not is_heading_1_to_3("Normal")
    assert not is_heading_1_to_3("Heading 4")
    assert not should_review_paragraph(
        WordDocumentParagraph(index=1, text="för kort", style="Normal")
    )
    assert not should_review_paragraph(
        WordDocumentParagraph(
            index=2,
            text="Detta är en tillräckligt lång brödtext.",
            style="Heading 2",
        )
    )
    assert should_review_paragraph(
        WordDocumentParagraph(
            index=3,
            text="Detta är en tillräckligt lång brödtext.",
            style="Normal",
        )
    )


def test_word_paragraph_review_is_registered_and_not_a_panel_session_method():
    assert WORD_REVIEW_METHOD in DELIBERATION_METHODS
    assert DELIBERATION_METHODS[WORD_REVIEW_METHOD] is word_paragraph_review


@pytest.mark.asyncio
async def test_word_paragraph_review_rejects_panel_session_dispatch():
    with pytest.raises(ValueError, match="expertgranskning_word_review"):
        await word_paragraph_review(None, PanelSession(id="ps_word"), {})  # type: ignore[arg-type]


async def _create_expert_panel(client: AsyncClient) -> int:
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    bolag_id = next(row["id"] for row in listed.json() if row["slug"] == BOLAG_DEMO_KUND_SLUG)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    assert experts.status_code == 200
    expert_ids = [row["id"] for row in experts.json()[:2]]
    assert len(expert_ids) >= 2
    created = await client.post(
        "/populations",
        json={
            "kind": "expert_panel",
            "name": "Word-review testpanel",
            "include_persona_ids": expert_ids,
            "recipe": {"size": len(expert_ids), "dist": {}},
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _document_with_two_body_paragraphs() -> dict:
    return {
        "doc_id": "doc-word-1",
        "sections": [
            {
                "heading": "Inledning",
                "heading_style": "Heading 1",
                "heading_paragraph_index": 0,
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "Första stycket är tillräckligt långt för granskning.",
                        "style": "Normal",
                    },
                    {
                        "index": 2,
                        "text": "kort",
                        "style": "Normal",
                    },
                    {
                        "index": 3,
                        "text": "Detta ser ut som en underrubrik i dokumentet.",
                        "style": "Heading 2",
                    },
                    {
                        "index": 4,
                        "text": "Andra stycket är också tillräckligt långt för granskning.",
                        "style": "Normal",
                    },
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_word_job_post_returns_job_id_without_running(client: AsyncClient):
    panel_id = await _create_expert_panel(client)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await client.post(
            "/expertgranskning/word-jobs",
            json={"panel_id": panel_id, **_document_with_two_body_paragraphs()},
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        assert job_id.startswith("job_")
        fetched = await client.get(f"/jobs/{job_id}")
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["kind"] == WORD_JOB_KIND
        assert body["status"] == "pending"
        assert "kund_id" not in started.json()
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_word_review_is_sequential_and_commits_before_next_call(client_db):
    client, factory = client_db
    panel_id = await _create_expert_panel(client)
    call_log: list[tuple[str, int, list[int]]] = []

    async def completer(messages, response_model):
        async with factory() as session:
            rows = (
                await session.execute(
                    select(ExpertgranskningResult).order_by(
                        ExpertgranskningResult.created_at
                    )
                )
            ).scalars().all()
            call_log.append(
                (
                    response_model.__name__,
                    len(rows),
                    [row.paragraph_index for row in rows],
                )
            )
        user = messages[-1]["content"]
        if response_model is WordParagraphComments:
            if "Första stycket" in user:
                return WordParagraphComments(
                    comments=[
                        WordParagraphComment(
                            expert_id="jurist",
                            expert_namn="Juristen",
                            kommentar="Första stycket behöver skärpas.",
                        )
                    ]
                )
            if "Andra stycket" in user:
                return WordParagraphComments(
                    comments=[
                        WordParagraphComment(
                            expert_id="ekonom",
                            expert_namn="Ekonomen",
                            kommentar="Andra stycket är otydligt om kostnad.",
                        )
                    ]
                )
            raise AssertionError(f"Unexpected paragraph prompt: {user}")
        if response_model is WordHeadingAssessment:
            assert "Första stycket" in user
            assert "kort" in user
            assert "underrubrik" in user
            assert "Andra stycket" in user
            return WordHeadingAssessment(forslag="Tydligare inledning")
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await client.post(
            "/expertgranskning/word-jobs",
            json={"panel_id": panel_id, **_document_with_two_body_paragraphs()},
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        await jobs_service._run_job(job_id)

        job = await client.get(f"/jobs/{job_id}")
        assert job.status_code == 200
        payload = job.json()
        assert payload["status"] == "succeeded", payload.get("error")
        assert payload["result"]["method"] == WORD_REVIEW_METHOD
        assert payload["result"]["paragraph_reviews"] == 2
        assert payload["result"]["heading_reviews"] == 1
        assert payload["kind"] == WORD_JOB_KIND

        results = await client.get(f"/expertgranskning/word-jobs/{job_id}/results")
        assert results.status_code == 200
        rows = results.json()
        assert [row["paragraph_index"] for row in rows] == [0, 1, 4]
        assert [row["is_heading_suggestion"] for row in rows] == [True, False, False]
        heading = next(row for row in rows if row["is_heading_suggestion"])
        body_rows = [row for row in rows if not row["is_heading_suggestion"]]
        assert body_rows[0]["kommentar"] == "Första stycket behöver skärpas."
        assert body_rows[1]["kommentar"] == "Andra stycket är otydligt om kostnad."
        assert heading["kommentar"] == "Tydligare inledning"
        assert all(row["comment_id"] is None for row in rows)
        assert all(row["status"] == "pending" for row in rows)

        assert [name for name, _count, _indexes in call_log] == [
            "WordParagraphComments",
            "WordParagraphComments",
            "WordHeadingAssessment",
        ]
        assert call_log[0][1] == 0
        assert call_log[1][2] == [1]
        assert call_log[2][2] == [1, 4]

        async with factory() as session:
            stored = await session.get(Job, job_id)
            assert stored is not None
            assert stored.kind == WORD_JOB_KIND
            panels = (await session.execute(select(PanelSession))).scalars().all()
            assert panels == []
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_word_review_heading_once_per_section_after_last_paragraph(client_db):
    client, factory = client_db
    panel_id = await _create_expert_panel(client)
    heading_seen_at: list[int] = []

    async def completer(messages, response_model):
        async with factory() as session:
            count = len(
                (
                    await session.execute(select(ExpertgranskningResult))
                ).scalars().all()
            )
        if response_model is WordHeadingAssessment:
            heading_seen_at.append(count)
            return WordHeadingAssessment(forslag=None)
        return WordParagraphComments(
            comments=[
                WordParagraphComment(
                    expert_id="jurist",
                    expert_namn="Juristen",
                    kommentar="En kommentar.",
                )
            ]
        )

    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        started = await client.post(
            "/expertgranskning/word-jobs",
            json={
                "panel_id": panel_id,
                "sections": [
                    {
                        "heading": "A",
                        "heading_paragraph_index": 0,
                        "paragraphs": [
                            {
                                "index": 1,
                                "text": "Första avsnittets enda granskningsbara stycke här.",
                                "style": "Normal",
                            }
                        ],
                    },
                    {
                        "heading": "B",
                        "heading_paragraph_index": 2,
                        "paragraphs": [
                            {
                                "index": 3,
                                "text": "Andra avsnittets enda granskningsbara stycke här.",
                                "style": "Normal",
                            }
                        ],
                    },
                ],
            },
        )
        assert started.status_code == 202, started.text
        await jobs_service._run_job(started.json()["job_id"])
        assert heading_seen_at == [1, 2]
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_word_result_patch_writes_comment_id(client: AsyncClient):
    panel_id = await _create_expert_panel(client)

    async def completer(_messages, response_model):
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        return WordParagraphComments(
            comments=[
                WordParagraphComment(
                    expert_id="jurist",
                    expert_namn="Juristen",
                    kommentar="En kommentar att fästa.",
                )
            ]
        )

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
            json={"comment_id": "word-comment-42"},
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["comment_id"] == "word-comment-42"
        assert body["status"] == "posted"
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_word_job_rejects_foreign_panel(user_client: AsyncClient, client: AsyncClient):
    listed = await client.get("/kunder")
    bolag_id = next(row["id"] for row in listed.json() if row["slug"] == BOLAG_DEMO_KUND_SLUG)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    expert_ids = [row["id"] for row in experts.json()[:1]]
    bolag_token = mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")
    bolag_created = await client.post(
        "/populations",
        headers={"Authorization": f"Bearer {bolag_token}"},
        json={
            "kind": "expert_panel",
            "name": "Bolag word panel",
            "include_persona_ids": expert_ids,
            "recipe": {"size": 1, "dist": {}},
        },
    )
    assert bolag_created.status_code == 201, bolag_created.text
    denied = await user_client.post(
        "/expertgranskning/word-jobs",
        json={
            "panel_id": bolag_created.json()["id"],
            "sections": [
                {
                    "heading": "X",
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
    assert denied.status_code == 403
