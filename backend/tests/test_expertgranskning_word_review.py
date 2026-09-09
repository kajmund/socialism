"""Expertgranskning Word review: list_string, batches, raise-hand, rewrite."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database.models import ExpertgranskningResult, PanelSession
from app.llm import set_structured_completer
from app.services import jobs as jobs_service
from app.services.expertgranskning import WORD_JOB_KIND
from app.services.expertgranskning.schemas import (
    WORD_MAX_PARAGRAPH_LEN,
    WORD_MAX_PARAGRAPHS,
    ExpertgranskningWordJobCreate,
    ExpertgranskningWordJobRequest,
    WordDocumentParagraph,
    WordDocumentSection,
    WordExpertComment,
    WordExpertRaiseHand,
    WordHeadingAssessment,
    WordRewriteSuggestion,
)
from app.services.expertgranskning.watch import reviewed_text_from_job_request
from app.services.expertgranskning.word_review import (
    _document_brief,
    build_batches,
    is_heading_1_to_3,
    rewrite_suggestion_or_none,
    should_review_paragraph,
    word_paragraph_review,
)
from app.services.kund_store import BOLAG_DEMO_KUND_SLUG
from tests.conftest import (
    BOLAG_USER_ID,
    TEST_CUSTOMER_ID,
    USER_USER_ID,
    mint_access_token,
)

DEFAULT_EXPERT_LABELS = ["Finansiell analytiker", "Jurist"]


def _identity_label(messages: list[dict]) -> str:
    for message in messages:
        if message.get("role") != "system":
            continue
        content = message.get("content") or ""
        for label in DEFAULT_EXPERT_LABELS:
            if f"Du deltar som {label}" in content or f"You participate as {label}" in content:
                return label
    return ""


def _batch_indexes_from_user(user: str) -> list[int]:
    marker = "Den här batchen"
    if marker not in user:
        marker = "This batch"
    chunk = user.split(marker, 1)[-1]
    return [
        int(line.split("]", 1)[0].lstrip("["))
        for line in chunk.splitlines()
        if line.startswith("[") and "]" in line
    ]


async def _create_expert_panel(client: AsyncClient, *, n: int = 2) -> int:
    listed = await client.get("/personas", params={"kind": "expert"})
    assert listed.status_code == 200, listed.text
    by_name = {row["name"]: row["id"] for row in listed.json()}
    wanted = DEFAULT_EXPERT_LABELS[:n]
    missing = [name for name in wanted if name not in by_name]
    assert not missing, f"seeded expert personas missing: {missing}"
    persona_ids = [by_name[name] for name in wanted]
    created = await client.post(
        "/populations",
        json={
            "kind": "expert_panel",
            "name": f"Word review panel {uuid.uuid4().hex[:8]}",
            "include_persona_ids": persona_ids,
            "recipe": {"size": n, "dist": {}},
        },
    )
    assert created.status_code == 201, created.text
    return int(created.json()["id"])


async def _create_bolag_expert_panel(client: AsyncClient, *, n: int = 1) -> tuple[int, int]:
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    bolag_id = next(row["id"] for row in listed.json() if row["slug"] == BOLAG_DEMO_KUND_SLUG)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    assert experts.status_code == 200
    expert_ids = [row["id"] for row in experts.json()[:n]]
    assert len(expert_ids) >= n, "seeded bolag expert personas missing"
    token = mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")
    created = await client.post(
        "/populations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "kind": "expert_panel",
            "name": f"Bolag word panel {uuid.uuid4().hex[:8]}",
            "include_persona_ids": expert_ids,
            "recipe": {"size": n, "dist": {}},
        },
    )
    assert created.status_code == 201, created.text
    return int(created.json()["id"]), int(bolag_id)


async def _committed_result_count(job_id: str) -> int:
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        return len(
            (
                await session.execute(
                    select(ExpertgranskningResult).where(
                        ExpertgranskningResult.job_id == job_id
                    )
                )
            )
            .scalars()
            .all()
        )


def _payload(*, heading="Avtal", paragraphs: list[WordDocumentParagraph], **extra):
    return {
        "panel_id": extra.get("panel_id", 1),
        "doc_id": extra.get("doc_id", "doc-1"),
        "sections": [
            {
                "heading": heading,
                "heading_style": extra.get("heading_style", "Heading 1"),
                "heading_paragraph_index": extra.get("heading_paragraph_index", 0),
                "paragraphs": [p.model_dump() for p in paragraphs],
            }
        ],
    }


def _para(index: int, text: str, *, style="Normal", list_string=""):
    return WordDocumentParagraph(
        index=index, text=text, style=style, list_string=list_string
    )


def test_list_string_defaults_empty_for_legacy_clients():
    para = WordDocumentParagraph(index=3, text="Brödtext", style="Normal")
    assert para.list_string == ""


def test_document_brief_indexes_match_paragraph_index():
    payload = ExpertgranskningWordJobRequest.model_validate(
        {
            "panel_id": 1,
            "customer_id": 1,
            "owner_user_id": "u1",
            "sections": [
                {
                    "heading": "Kontakt",
                    "heading_style": "Heading 1",
                    "heading_paragraph_index": 10,
                    "paragraphs": [
                        {
                            "index": 11,
                            "text": "   ",
                            "style": "Normal",
                            "list_string": "",
                        },
                        {
                            "index": 12,
                            "text": "Parterna har utsett kontaktpersoner.",
                            "style": "Normal",
                            "list_string": "2.1.",
                        },
                    ],
                }
            ],
        }
    )
    brief = _document_brief(payload)
    assert "[11]" not in brief
    assert "[12] 2.1. Parterna har utsett kontaktpersoner." in brief
    assert brief.count("[12]") == 1


def test_document_brief_skips_empty_heading_line():
    payload = ExpertgranskningWordJobRequest.model_validate(
        {
            "panel_id": 1,
            "customer_id": 1,
            "owner_user_id": "u1",
            "sections": [
                {
                    "heading": "",
                    "heading_style": "",
                    "heading_paragraph_index": 0,
                    "paragraphs": [
                        {
                            "index": 0,
                            "text": "Ingress utan egen rubrik i dokumentet.",
                            "style": "Normal",
                            "list_string": "",
                        }
                    ],
                }
            ],
        }
    )
    assert _document_brief(payload) == "[0] Ingress utan egen rubrik i dokumentet."


def test_build_batches_keeps_clause_together_even_over_max():
    section = WordDocumentSection(
        heading="Ansvar",
        heading_style="Heading 1",
        heading_paragraph_index=0,
        paragraphs=[
            _para(
                1 + i - 1,
                f"Detta är ett giltigt stycke under klausul fem punkt {i}.",
                list_string=f"5.{i}.",
            )
            for i in range(1, 6)
        ],
    )
    batches = build_batches(section, max_size=4)
    assert len(batches) == 1
    assert [p.index for p in batches[0]] == [1, 2, 3, 4, 5]


def test_build_batches_unnumbered_splits_four_four_two():
    section = WordDocumentSection(
        heading="Bakgrund",
        heading_style="Heading 1",
        heading_paragraph_index=0,
        paragraphs=[
            _para(i, f"Detta är ett giltigt onumrerat stycke nummer {i}.")
            for i in range(1, 11)
        ],
    )
    batches = build_batches(section, max_size=4)
    assert [[p.index for p in batch] for batch in batches] == [
        [1, 2, 3, 4],
        [5, 6, 7, 8],
        [9, 10],
    ]


def test_build_batches_covers_reviewable_paragraphs_once():
    section = WordDocumentSection(
        heading="Mix",
        heading_style="Heading 1",
        heading_paragraph_index=0,
        paragraphs=[
            _para(1, "Detta är ett giltigt stycke att granska."),
            _para(2, "kort", style="Heading 2"),
            _para(3, "Detta andra stycke är också giltigt nog."),
            _para(4, "a b"),
        ],
    )
    reviewable = [p.index for p in section.paragraphs if should_review_paragraph(p)]
    batched = [p.index for batch in build_batches(section) for p in batch]
    assert batched == reviewable
    assert len(batched) == len(set(batched))


def test_should_review_and_heading_helpers_unchanged():
    assert should_review_paragraph(_para(1, "ett två tre fyra fem"))
    assert not should_review_paragraph(_para(2, "kort"))
    assert is_heading_1_to_3("Heading 2")
    assert rewrite_suggestion_or_none(
        WordRewriteSuggestion(ny_text="En rad.", motivering="ok")
    )
    assert (
        rewrite_suggestion_or_none(
            WordRewriteSuggestion(ny_text="rad1\nrad2", motivering="x")
        )
        is None
    )
    kept = WordRewriteSuggestion(
        ny_text="En rad.",
        motivering="Första skälet.\nAndra skälet.",
    )
    assert kept.motivering == "Första skälet.\nAndra skälet."
    assert rewrite_suggestion_or_none(kept) is not None


@pytest.mark.asyncio
async def test_word_paragraph_review_rejects_panel_session_dispatch():
    with pytest.raises(ValueError, match="expertgranskning_word_review"):
        await word_paragraph_review(None, PanelSession(id="ps_word"), {})  # type: ignore[arg-type]


def test_reviewed_text_from_job_request_walks_sections():
    request = {
        "sections": [
            {
                "heading": "Inledning",
                "heading_paragraph_index": 0,
                "paragraphs": [
                    {"index": 1, "text": "Första stycket."},
                    {"index": 4, "text": "Andra stycket."},
                ],
            }
        ]
    }
    assert reviewed_text_from_job_request(request, 0) == "Inledning"
    assert reviewed_text_from_job_request(request, 1) == "Första stycket."
    assert reviewed_text_from_job_request(request, 4) == "Andra stycket."
    assert reviewed_text_from_job_request(request, 9) is None
    assert reviewed_text_from_job_request(None, 1) is None
    implicit = {
        "sections": [
            {
                "heading": "",
                "heading_paragraph_index": 0,
                "paragraphs": [{"index": 0, "text": "Ingress utan rubrik."}],
            }
        ]
    }
    assert reviewed_text_from_job_request(implicit, 0) == "Ingress utan rubrik."


def test_word_job_rejects_unsupported_locale_and_oversized_document():
    from pydantic import ValidationError

    section = {
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
    with pytest.raises(ValidationError):
        ExpertgranskningWordJobCreate(panel_id=1, locale="en-US", sections=[section])
    with pytest.raises(ValidationError):
        ExpertgranskningWordJobCreate(
            panel_id=1,
            sections=[
                {
                    "heading": "X",
                    "heading_paragraph_index": 0,
                    "paragraphs": [
                        {
                            "index": i,
                            "text": "Detta stycke är tillräckligt långt för granskning.",
                            "style": "Normal",
                        }
                        for i in range(WORD_MAX_PARAGRAPHS + 1)
                    ],
                }
            ],
        )
    with pytest.raises(ValidationError):
        ExpertgranskningWordJobCreate(
            panel_id=1,
            sections=[
                {
                    "heading": "X",
                    "heading_paragraph_index": 0,
                    "paragraphs": [
                        {
                            "index": 1,
                            "text": "x" * (WORD_MAX_PARAGRAPH_LEN + 1),
                            "style": "Normal",
                        }
                    ],
                }
            ],
        )


@pytest.mark.asyncio
async def test_word_review_creates_job_without_running(client: AsyncClient):
    panel_id = await _create_expert_panel(client)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    response = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt.")],
        ),
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/results")
    assert listed.status_code == 200
    assert listed.json() == []


@pytest.mark.asyncio
async def test_word_review_rejects_foreign_panel(client: AsyncClient):
    panel_id = await _create_expert_panel(client)
    token = mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")
    response = await client.post(
        "/expertgranskning/word-jobs",
        headers={"Authorization": f"Bearer {token}"},
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt.")],
        ),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "kund_access_denied"


@pytest.mark.asyncio
async def test_word_review_raise_hand_then_comment_and_heading(client: AsyncClient):
    calls: list[str] = []

    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if response_model is WordExpertRaiseHand:
            calls.append("raise")
            return WordExpertRaiseHand(paragraph_indexes=_batch_indexes_from_user(user)[:1])
        if response_model is WordExpertComment:
            calls.append(f"comment:{_identity_label(messages)}")
            return WordExpertComment(kommentar="En konkret kommentar.")
        if response_model is WordHeadingAssessment:
            calls.append("heading")
            assert "Nuvarande rubrik:" in user or "Current heading:" in user
            return WordHeadingAssessment(forslag="Tydligare rubrik")
        if response_model is WordRewriteSuggestion:
            calls.append("rewrite")
            return WordRewriteSuggestion(ny_text="Ny formulering.", motivering="Samma fix.")
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)

    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/results")
    assert listed.status_code == 200
    rows = listed.json()
    comments = [row for row in rows if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]]
    headings = [row for row in rows if row["is_heading_suggestion"]]
    rewrites = [row for row in rows if row["is_rewrite_suggestion"]]
    assert len(comments) == 2
    assert {row["expert_namn"] for row in comments} == set(DEFAULT_EXPERT_LABELS)
    assert headings[0]["kommentar"] == "Tydligare rubrik"
    assert rewrites[0]["foreslagen_text"] == "Ny formulering."
    assert calls.count("raise") == 2
    assert calls.count("heading") == 1
    assert calls.count("rewrite") == 1
    assert sum(1 for call in calls if call.startswith("comment:")) == 2

    job = await client.get(f"/jobs/{job_id}")
    assert job.json()["result"]["paragraph_reviews"] == 1


@pytest.mark.asyncio
async def test_word_review_sends_document_brief_once_per_call(client: AsyncClient):
    captured: list[list[dict]] = []

    async def completer(messages, response_model):
        captured.append(messages)
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(paragraph_indexes=[])
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    await jobs_service._run_job(created.json()["job_id"])
    raise_payloads = [
        messages
        for messages in captured
        if "Den här batchen" in messages[-1]["content"]
        or "This batch" in messages[-1]["content"]
    ]
    assert raise_payloads
    heading_line = "[0] Heading 1 Avtal"
    body_line = "[1] Detta stycke är tillräckligt långt för granskning."
    for messages in raise_payloads:
        systems = [
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "system"
        ]
        user = messages[-1]["content"]
        assert sum(1 for text in systems if heading_line in text and body_line in text) == 1
        assert heading_line not in user
        assert "Dokumentet i sin helhet" not in user
        assert "{document_brief}" not in user


@pytest.mark.asyncio
async def test_word_review_empty_raise_hand_writes_no_comment(client: AsyncClient):
    comment_calls = 0

    async def completer(messages, response_model):
        nonlocal comment_calls
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(paragraph_indexes=[])
        if response_model is WordExpertComment:
            comment_calls += 1
            return WordExpertComment(kommentar="borde inte köras")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    await jobs_service._run_job(created.json()["job_id"])
    rows = (
        await client.get(
            f"/expertgranskning/word-jobs/{created.json()['job_id']}/results"
        )
    ).json()
    assert comment_calls == 0
    assert [row for row in rows if not row["is_heading_suggestion"]] == []


@pytest.mark.asyncio
async def test_word_review_out_of_batch_indexes_are_dropped(client: AsyncClient):
    comment_calls = 0

    async def completer(messages, response_model):
        nonlocal comment_calls
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(paragraph_indexes=[99])
        if response_model is WordExpertComment:
            comment_calls += 1
            return WordExpertComment(kommentar="fel ankare")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    await jobs_service._run_job(created.json()["job_id"])
    assert comment_calls == 0


@pytest.mark.asyncio
async def test_word_review_empty_comment_is_not_written(client: AsyncClient):
    async def completer(messages, response_model):
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(paragraph_indexes=_batch_indexes_from_user(messages[-1]["content"]))
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="   ")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    assert [row for row in rows if not row["is_heading_suggestion"]] == []


@pytest.mark.asyncio
async def test_word_review_commits_after_batch_not_after_each_call(client: AsyncClient):
    seen_during_rewrite: list[int] = []
    seen_during_heading: list[int] = []
    job_holder: dict[str, str] = {}

    async def completer(messages, response_model):
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(
                paragraph_indexes=_batch_indexes_from_user(messages[-1]["content"])[:1]
            )
        if response_model is WordExpertComment:
            return WordExpertComment(
                kommentar=f"Kommentar från {_identity_label(messages)}."
            )
        if response_model is WordRewriteSuggestion:
            seen_during_rewrite.append(await _committed_result_count(job_holder["id"]))
            return WordRewriteSuggestion(ny_text="Gemensam rad.", motivering="Samma")
        if response_model is WordHeadingAssessment:
            seen_during_heading.append(await _committed_result_count(job_holder["id"]))
            return WordHeadingAssessment(forslag=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    job_holder["id"] = created.json()["job_id"]
    await jobs_service._run_job(job_holder["id"])
    assert seen_during_rewrite == [0]
    assert seen_during_heading == [3]


@pytest.mark.asyncio
async def test_word_review_no_rewrite_with_one_comment(client: AsyncClient):
    rewrite_calls = 0

    async def completer(messages, response_model):
        nonlocal rewrite_calls
        label = _identity_label(messages)
        if response_model is WordExpertRaiseHand:
            if label == DEFAULT_EXPERT_LABELS[0]:
                return WordExpertRaiseHand(paragraph_indexes=[1])
            return WordExpertRaiseHand(paragraph_indexes=[])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Bara en röst.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            rewrite_calls += 1
            return WordRewriteSuggestion(ny_text="Ska inte ske.", motivering="x")
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    assert rewrite_calls == 0
    assert [row for row in rows if row["is_rewrite_suggestion"]] == []
    assert len([row for row in rows if not row["is_heading_suggestion"]]) == 1


@pytest.mark.asyncio
async def test_word_review_split_opinions_do_not_rewrite(client: AsyncClient):
    async def completer(messages, response_model):
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(paragraph_indexes=[1])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar=f"Olika syn från {_identity_label(messages)}.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text=None, motivering=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    assert [row for row in rows if row["is_rewrite_suggestion"]] == []


@pytest.mark.asyncio
async def test_word_review_converging_comments_write_rewrite(client: AsyncClient):
    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(paragraph_indexes=[1])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Skriv om till tydligare mening.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            assert "Kommentarer:" in user or "Comments:" in user
            return WordRewriteSuggestion(
                ny_text="Parterna ska utse kontaktpersoner.",
                motivering="Båda vill samma sak.",
            )
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    rewrite = next(row for row in rows if row["is_rewrite_suggestion"])
    assert rewrite["foreslagen_text"] == "Parterna ska utse kontaktpersoner."
    assert rewrite["kommentar"] == "Båda vill samma sak."


@pytest.mark.asyncio
async def test_word_review_patch_comment_id(client: AsyncClient):
    async def completer(messages, response_model):
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(paragraph_indexes=[1])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="ok")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text=None, motivering=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt för granskning.")],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    row_id = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()[0]["id"]
    patched = await client.patch(
        f"/expertgranskning/word-jobs/{job_id}/results/{row_id}",
        json={"comment_id": "w-1"},
    )
    assert patched.status_code == 200
    assert patched.json()["comment_id"] == "w-1"


@pytest.mark.asyncio
async def test_word_review_rejects_second_active_job_for_same_doc(client: AsyncClient):
    panel_id = await _create_expert_panel(client)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    first = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            doc_id="same-doc",
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt.")],
        ),
    )
    assert first.status_code == 202
    second = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            doc_id="same-doc",
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt.")],
        ),
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "word_review_already_running"


@pytest.mark.asyncio
async def test_latest_word_job_is_customer_scoped(client: AsyncClient):
    panel_id = await _create_expert_panel(client)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            doc_id="scoped-doc",
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt.")],
        ),
    )
    assert created.status_code == 202
    admin_latest = await client.get("/expertgranskning/word-jobs/latest?doc_id=scoped-doc")
    assert admin_latest.status_code == 200
    token = mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")
    bolag = await client.get(
        "/expertgranskning/word-jobs/latest?doc_id=scoped-doc",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bolag.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_run_bolag_panel(client: AsyncClient):
    panel_id, bolag_id = await _create_bolag_expert_panel(client)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    response = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt.")],
        ),
    )
    assert response.status_code == 202, response.text
    job = (await client.get(f"/jobs/{response.json()['job_id']}")).json()
    assert job["customer_id"] == bolag_id


@pytest.mark.asyncio
async def test_generic_jobs_path_rejects_foreign_panel(
    client: AsyncClient, user_token: str
):
    panel_id, _bolag_id = await _create_bolag_expert_panel(client)
    stolen = await client.post(
        "/jobs",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "kind": WORD_JOB_KIND,
            "request": {
                "panel_id": panel_id,
                "customer_id": TEST_CUSTOMER_ID,
                "owner_user_id": USER_USER_ID,
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
        },
    )
    assert stolen.status_code == 422
    assert "panel_id" in stolen.text


@pytest.mark.asyncio
async def test_latest_word_job_404_when_unknown(client: AsyncClient):
    missing = await client.get(
        "/expertgranskning/word-jobs/latest",
        params={"doc_id": "doc-does-not-exist"},
    )
    assert missing.status_code == 404
