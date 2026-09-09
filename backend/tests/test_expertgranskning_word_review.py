from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database.models import (
    ExpertgranskningResult,
    Job,
)
from app.llm import set_structured_completer
from app.services.expertgranskning.disposition import (
    DEFAULT_BATCH_SIZE,
    batch_reviewable_paragraphs,
    build_disposition,
    clause_group_key,
    extract_written_number,
    flatten_paragraphs,
    normalize_number,
)
from app.services.expertgranskning.schemas import (
    ExpertgranskningWordJobCreate,
    ExpertgranskningWordJobRequest,
    WordDocumentParagraph,
    WordDocumentSection,
    WordExpertBatchComments,
    WordExpertParagraphComment,
    WordHeadingAssessment,
    WordParagraphComment,
    WordParagraphComments,
    WordRaiseHand,
    WordRewriteAssessment,
    WordRewriteSuggestion,
)
from app.services.expertgranskning.word_review import (
    is_heading_1_to_3,
    paragraph_word_count,
    rewrite_suggestion_or_none,
    run_word_paragraph_review,
    run_word_paragraph_review_for_job,
    should_review_paragraph,
    word_paragraph_review,
)
from app.services import jobs as jobs_service
from app.services.kund_store import bolag_demo_customer_id, default_os_customer_id
from app.services.prompt_store import require_active_prompts
from tests.conftest import TEST_CUSTOMER_ID


def _para(
    index: int,
    text: str,
    *,
    style: str = "Normal",
    list_string: str | None = None,
) -> WordDocumentParagraph:
    return WordDocumentParagraph(index=index, text=text, style=style, list_string=list_string)


def _section(
    heading: str,
    heading_index: int,
    bodies: list[tuple[int, str]],
    *,
    heading_style: str = "Heading 1",
) -> WordDocumentSection:
    return WordDocumentSection(
        heading=heading,
        heading_paragraph_index=heading_index,
        paragraphs=[
            _para(heading_index, heading, style=heading_style),
            *[_para(index, text) for index, text in bodies],
        ],
    )


def _parse_batch_indexes(content: str) -> list[int]:
    start = content.rfind("Batch (endast dessa index är giltiga):")
    if start < 0:
        start = content.rfind("Batch:")
    if start < 0:
        start = content.rfind("Stycken att bedöma:")
    chunk = content[start:] if start >= 0 else content
    return [
        int(line[1 : line.index("]")])
        for line in chunk.splitlines()
        if line.startswith("[") and "]" in line
    ]


def _completer_factory(
    *,
    raise_indexes: list[int] | None = None,
    raise_all_experts: bool = False,
    comment_text: str = "En kommentar.",
    rewrite_suggestion: WordRewriteSuggestion | None = None,
    heading_text: str = "",
    fail_on_heading: bool = False,
) -> Callable[..., Any]:
    first_slot: str | None = None
    count = 0

    async def completer(messages: list[dict[str, str]], response_model: type) -> Any:
        nonlocal count, first_slot
        count += 1
        content = messages[-1]["content"]
        if response_model is WordRaiseHand:
            slot = ""
            for line in content.splitlines():
                if line.startswith("Aktuell expert:"):
                    slot = line.split(":", 1)[1].strip()
                    break
            if first_slot is None:
                first_slot = slot
            if raise_indexes is not None:
                return WordRaiseHand(paragraph_indexes=raise_indexes)
            if raise_all_experts or slot == first_slot:
                return WordRaiseHand(paragraph_indexes=_parse_batch_indexes(content))
            return WordRaiseHand(paragraph_indexes=[])
        if response_model is WordExpertBatchComments:
            indexes = raise_indexes if raise_indexes is not None else _parse_batch_indexes(content)
            return WordExpertBatchComments(
                comments=[
                    WordExpertParagraphComment(paragraph_index=index, kommentar=comment_text)
                    for index in indexes
                ]
            )
        if response_model is WordRewriteAssessment:
            return WordRewriteAssessment(omskrivning_forslag=rewrite_suggestion)
        if response_model is WordHeadingAssessment:
            if fail_on_heading:
                raise RuntimeError("heading failed")
            return WordHeadingAssessment(forslag=heading_text or None)
        raise AssertionError(f"unexpected model {response_model}")

    completer.call_count = lambda: count  # type: ignore[attr-defined]
    return completer


async def _create_expert_panel(client: AsyncClient) -> int:
    experts = await client.get(
        "/personas",
        params={"kind": "expert", "customer_id": TEST_CUSTOMER_ID},
    )
    assert experts.status_code == 200, experts.text
    expert_ids = [row["id"] for row in experts.json()[:2]]
    assert len(expert_ids) >= 2, experts.text
    created = await client.post(
        "/populations",
        json={
            "name": f"Expertgranskning testpanel {uuid4().hex[:8]}",
            "kind": "expert_panel",
            "include_persona_ids": expert_ids,
            "recipe": {"size": len(expert_ids), "dist": {}},
        },
    )
    assert created.status_code == 201, created.text
    return int(created.json()["id"])


def _job_payload(
    *,
    panel_id: int,
    customer_id: int,
    sections: list[WordDocumentSection],
) -> ExpertgranskningWordJobRequest:
    return ExpertgranskningWordJobRequest(
        panel_id=panel_id,
        customer_id=customer_id,
        owner_user_id="test-user",
        sections=sections,
    )


async def _job_row(session, job_id: str) -> Job:
    job = await session.get(Job, job_id)
    assert job is not None
    return job


async def _results_for_job(session, job_id: str) -> list[ExpertgranskningResult]:
    result = await session.execute(
        select(ExpertgranskningResult)
        .where(ExpertgranskningResult.job_id == job_id)
        .order_by(ExpertgranskningResult.created_at, ExpertgranskningResult.id)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_filter_skips_short_and_heading_paragraphs() -> None:
    assert paragraph_word_count("ett två tre fyra") == 4
    assert is_heading_1_to_3("Heading 2")
    assert is_heading_1_to_3("Rubrik 3")
    assert not should_review_paragraph(_para(0, "Kort", style="Normal"))
    assert not should_review_paragraph(_para(1, "Lång nog för granskning här", style="Heading 1"))
    assert should_review_paragraph(_para(2, "Detta stycke är tillräckligt långt", style="Normal"))


@pytest.mark.asyncio
async def test_word_paragraph_review_is_registered() -> None:
    assert word_paragraph_review.protocol == "word_paragraph_review"
    with pytest.raises(ValueError, match="expertgranskning_word_review"):
        await word_paragraph_review(object(), object(), {})  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_reviewable_batches_keep_clause_groups() -> None:
    paragraphs = [
        _para(0, "Ingress som är tillräckligt lång", style="Heading 1"),
        *[_para(i, f"Punkt {i} är tillräckligt långt") for i in range(1, 5)],
        _para(5, "8.1 Första underraden är tillräckligt lång", list_string="8.1"),
        _para(6, "8.2 Andra underraden är också tillräckligt lång", list_string="8.2"),
        _para(7, "9 Fristående punkt är tillräckligt lång", list_string="9"),
    ]
    reviewable = [p for p in paragraphs if should_review_paragraph(p)]
    batches = batch_reviewable_paragraphs(reviewable, size=4)
    assert [[p.index for p in batch] for batch in batches] == [[1, 2, 3, 4], [5, 6], [7]]


@pytest.mark.asyncio
async def test_disposition_uses_style_and_list_string() -> None:
    paragraphs = [
        _para(0, "Bakgrund", style="Heading 1"),
        _para(1, "8.1 Detta är tillräckligt långt", style="Normal", list_string="7.1"),
        _para(2, "Detta är också tillräckligt långt", style="Normal"),
    ]
    text = build_disposition(paragraphs)
    assert 'written="8.1"' in text
    assert 'list="7.1"' in text
    assert 'computed="7.1"' in text
    assert "MISMATCH" in text
    assert "Heading 1" in text


@pytest.mark.asyncio
async def test_extract_written_number_from_text_or_list_string() -> None:
    assert extract_written_number("7.1 Ansvar") == "7.1"
    assert extract_written_number("Ingen siffra här") == ""
    assert normalize_number("7.1") == "7.1"
    assert clause_group_key(_para(0, "text", list_string="8.2")) == "8"


@pytest.mark.asyncio
async def test_rewrite_suggestion_requires_single_paragraph() -> None:
    assert (
        rewrite_suggestion_or_none(
            WordParagraphComments(
                comments=[],
                omskrivning_forslag=WordRewriteSuggestion(
                    ny_text=" Ny formulering. ",
                    motivering="Samma riktning.",
                ),
            )
        )
        is not None
    )
    assert (
        rewrite_suggestion_or_none(
            WordParagraphComments(
                comments=[],
                omskrivning_forslag=WordRewriteSuggestion(
                    ny_text="rad ett\nrad två",
                    motivering="Samma riktning.",
                ),
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_empty_raise_writes_no_comments(client_db) -> None:
    client, factory = client_db
    panel_id = await _create_expert_panel(client)
    payload = _job_payload(
        panel_id=panel_id,
        customer_id=TEST_CUSTOMER_ID,
        sections=[_section("Avsnitt", 0, [(1, "Detta stycke är tillräckligt långt")])],
    )
    completer = _completer_factory(raise_indexes=[])
    set_structured_completer(completer)
    try:
        async with factory() as session:
            job = Job(
                id="job_empty_raise",
                kind="expertgranskning_word_review",
                status="running",
                customer_id=TEST_CUSTOMER_ID,
                request=payload.model_dump(),
            )
            session.add(job)
            await session.commit()
            prompts = await require_active_prompts(
                session, customer_id=TEST_CUSTOMER_ID, module="expertgranskning", language="sv"
            )
            stats = await run_word_paragraph_review(session, job, payload, prompts)
            rows = await _results_for_job(session, job.id)
        assert stats["result_count"] == 0
        assert rows == []
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_out_of_batch_raise_is_dropped(client_db) -> None:
    client, factory = client_db
    panel_id = await _create_expert_panel(client)
    payload = _job_payload(
        panel_id=panel_id,
        customer_id=TEST_CUSTOMER_ID,
        sections=[_section("Avsnitt", 0, [(1, "Detta stycke är tillräckligt långt")])],
    )
    completer = _completer_factory(raise_indexes=[99])
    set_structured_completer(completer)
    try:
        async with factory() as session:
            job = Job(
                id="job_oob_raise",
                kind="expertgranskning_word_review",
                status="running",
                customer_id=TEST_CUSTOMER_ID,
                request=payload.model_dump(),
            )
            session.add(job)
            await session.commit()
            prompts = await require_active_prompts(
                session, customer_id=TEST_CUSTOMER_ID, module="expertgranskning", language="sv"
            )
            stats = await run_word_paragraph_review(session, job, payload, prompts)
            rows = await _results_for_job(session, job.id)
        assert stats["result_count"] == 0
        assert rows == []
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_word_review_runs_reviewable_paragraphs_then_heading(client_db) -> None:
    client, factory = client_db
    panel_id = await _create_expert_panel(client)
    payload = _job_payload(
        panel_id=panel_id,
        customer_id=TEST_CUSTOMER_ID,
        sections=[
            _section(
                "Inledning",
                0,
                [(1, "Detta stycke är tillräckligt långt"), (2, "Nej"), (3, "Kort")],
            ),
            _section("Slut", 4, [(5, "Också detta stycke är tillräckligt långt")]),
        ],
    )
    completer = _completer_factory(heading_text="Ny rubrik")
    set_structured_completer(completer)
    try:
        async with factory() as session:
            job = Job(
                id="job_seq",
                kind="expertgranskning_word_review",
                status="running",
                customer_id=TEST_CUSTOMER_ID,
                request=payload.model_dump(),
            )
            session.add(job)
            await session.commit()
            prompts = await require_active_prompts(
                session, customer_id=TEST_CUSTOMER_ID, module="expertgranskning", language="sv"
            )
            await run_word_paragraph_review(session, job, payload, prompts)
            rows = await _results_for_job(session, job.id)
        comments = [row for row in rows if not row.is_heading_suggestion]
        headings = [row for row in rows if row.is_heading_suggestion]
        assert {row.paragraph_index for row in comments} == {1, 5}
        assert {row.paragraph_index for row in headings} == {0, 4}
        assert headings[0].kommentar == "Ny rubrik"
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_heading_review_runs_once_after_last_raw_paragraph(client_db) -> None:
    client, factory = client_db
    panel_id = await _create_expert_panel(client)
    payload = _job_payload(
        panel_id=panel_id,
        customer_id=TEST_CUSTOMER_ID,
        sections=[
            _section("Ett", 0, [(1, "Detta stycke är tillräckligt långt")]),
            _section("Två", 2, [(3, "Också detta stycke är tillräckligt långt")]),
        ],
    )
    completer = _completer_factory(heading_text="Ny rubrik")
    set_structured_completer(completer)
    try:
        async with factory() as session:
            job = Job(
                id="job_head",
                kind="expertgranskning_word_review",
                status="running",
                customer_id=TEST_CUSTOMER_ID,
                request=payload.model_dump(),
            )
            session.add(job)
            await session.commit()
            prompts = await require_active_prompts(
                session, customer_id=TEST_CUSTOMER_ID, module="expertgranskning", language="sv"
            )
            stats = await run_word_paragraph_review(session, job, payload, prompts)
        assert stats["heading_reviews"] == 2
        assert stats["paragraph_reviews"] == 2
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_rewrite_is_additive_when_experts_converge(client_db) -> None:
    client, factory = client_db
    panel_id = await _create_expert_panel(client)
    payload = _job_payload(
        panel_id=panel_id,
        customer_id=TEST_CUSTOMER_ID,
        sections=[_section("Avsnitt", 0, [(1, "Detta stycke är tillräckligt långt")])],
    )
    completer = _completer_factory(
        raise_all_experts=True,
        rewrite_suggestion=WordRewriteSuggestion(
            ny_text="Ny formulering.",
            motivering="Samma riktning.",
        ),
    )
    set_structured_completer(completer)
    try:
        async with factory() as session:
            job = Job(
                id="job_rw_yes",
                kind="expertgranskning_word_review",
                status="running",
                customer_id=TEST_CUSTOMER_ID,
                request=payload.model_dump(),
            )
            session.add(job)
            await session.commit()
            prompts = await require_active_prompts(
                session, customer_id=TEST_CUSTOMER_ID, module="expertgranskning", language="sv"
            )
            await run_word_paragraph_review(session, job, payload, prompts)
            rows = await _results_for_job(session, job.id)
        comments = [row for row in rows if not row.is_rewrite_suggestion]
        rewrites = [row for row in rows if row.is_rewrite_suggestion]
        assert len(comments) == 2
        assert len(rewrites) == 1
        assert rewrites[0].foreslagen_text == "Ny formulering."
        assert rewrites[0].kommentar == "Samma riktning."
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_rewrite_skipped_when_experts_split(client_db) -> None:
    client, factory = client_db
    panel_id = await _create_expert_panel(client)
    payload = _job_payload(
        panel_id=panel_id,
        customer_id=TEST_CUSTOMER_ID,
        sections=[_section("Avsnitt", 0, [(1, "Detta stycke är tillräckligt långt")])],
    )
    completer = _completer_factory(raise_all_experts=True, rewrite_suggestion=None)
    set_structured_completer(completer)
    try:
        async with factory() as session:
            job = Job(
                id="job_rw_no",
                kind="expertgranskning_word_review",
                status="running",
                customer_id=TEST_CUSTOMER_ID,
                request=payload.model_dump(),
            )
            session.add(job)
            await session.commit()
            prompts = await require_active_prompts(
                session, customer_id=TEST_CUSTOMER_ID, module="expertgranskning", language="sv"
            )
            await run_word_paragraph_review(session, job, payload, prompts)
            rows = await _results_for_job(session, job.id)
        assert [row.is_rewrite_suggestion for row in rows] == [False, False]
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_word_job_writes_results_incrementally(client: AsyncClient) -> None:
    panel_id = await _create_expert_panel(client)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    completer = _completer_factory()
    set_structured_completer(completer)
    try:
        created = await client.post(
            "/expertgranskning/word-jobs",
            json=ExpertgranskningWordJobCreate(
                panel_id=panel_id,
                sections=[_section("Avsnitt", 0, [(1, "Detta stycke är tillräckligt långt")])],
            ).model_dump(),
        )
        assert created.status_code == 202, created.text
        job_id = created.json()["job_id"]
        await run_word_paragraph_review_for_job(job_id)
        rows = await client.get(f"/expertgranskning/word-jobs/{job_id}/results")
        assert rows.status_code == 200
        assert len(rows.json()) == 1
        assert rows.json()[0]["reviewed_text"].startswith("Detta stycke")
        job = await client.get(f"/jobs/{job_id}")
        assert job.status_code == 200
        assert job.json()["status"] == "succeeded"
        assert job.json()["result"]["paragraph_reviews"] == 1
    finally:
        jobs_service.set_schedule_hook(None)
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_word_job_fails_loudly_and_keeps_written_rows(client: AsyncClient) -> None:
    panel_id = await _create_expert_panel(client)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    completer = _completer_factory(fail_on_heading=True)
    set_structured_completer(completer)
    try:
        created = await client.post(
            "/expertgranskning/word-jobs",
            json=ExpertgranskningWordJobCreate(
                panel_id=panel_id,
                sections=[
                    _section("Ett", 0, [(1, "Detta stycke är tillräckligt långt")]),
                    _section("Två", 2, [(3, "Också detta stycke är tillräckligt långt")]),
                ],
            ).model_dump(),
        )
        job_id = created.json()["job_id"]
        with pytest.raises(RuntimeError, match="heading failed"):
            await run_word_paragraph_review_for_job(job_id)
        rows = await client.get(f"/expertgranskning/word-jobs/{job_id}/results")
        assert rows.status_code == 200
        assert len(rows.json()) == 1
    finally:
        jobs_service.set_schedule_hook(None)
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_word_review_rejects_oversized_document(client: AsyncClient) -> None:
    panel_id = await _create_expert_panel(client)
    huge = "ord " * 6_000
    response = await client.post(
        "/expertgranskning/word-jobs",
        json={
            "panel_id": panel_id,
            "sections": [
                {
                    "heading": "Stort",
                    "heading_paragraph_index": 0,
                    "paragraphs": [
                        {"index": 0, "text": "Stort", "style": "Heading 1"},
                        {"index": 1, "text": huge, "style": "Normal"},
                    ],
                }
            ],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_word_review_rejects_cross_tenant_panel_via_jobs(
    client: AsyncClient, client_db
) -> None:
    _client, factory = client_db
    panel_id = await _create_expert_panel(client)
    async with factory() as session:
        bolag_id = await bolag_demo_customer_id(session)
        os_id = await default_os_customer_id(session)
        assert bolag_id != os_id
    payload = {
        "kind": "expertgranskning_word_review",
        "customer_id": bolag_id,
        "request": _job_payload(
            panel_id=panel_id,
            customer_id=bolag_id,
            sections=[_section("Avsnitt", 0, [(1, "Detta stycke är tillräckligt långt")])],
        ).model_dump(),
    }
    response = await client.post("/jobs", json=payload)
    assert response.status_code == 422
    assert "panel" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_flatten_and_document_text_helpers() -> None:
    sections = [_section("Avsnitt", 0, [(1, "Detta stycke är tillräckligt långt")])]
    paragraphs = flatten_paragraphs(sections)
    assert [p.index for p in paragraphs] == [0, 1]
    from app.services.expertgranskning.disposition import document_text_from_sections

    text = document_text_from_sections(sections)
    assert "Avsnitt" in text
    assert "Detta stycke" in text
    assert DEFAULT_BATCH_SIZE == 4
