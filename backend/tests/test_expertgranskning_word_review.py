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
from app.services.expertgranskning.comment_convergence import (
    WordObservation,
    apply_word_comment_convergence,
    choose_specific_anchor,
    collapse_intra_expert_duplicates,
    comments_dissent,
)
from app.services.expertgranskning.schemas import (
    WORD_MAX_PARAGRAPH_LEN,
    WORD_MAX_PARAGRAPHS,
    ExpertgranskningWordJobCreate,
    ExpertgranskningWordJobRequest,
    WordBatchModeration,
    WordCommentConvergence,
    WordConvergedIssue,
    WordDocumentParagraph,
    WordDocumentSection,
    WordExpertComment,
    WordExpertRaiseHand,
    WordHeadingAssessment,
    WordRewriteSuggestion,
    WordReviewQuestion,
)
from app.services.expertgranskning.watch import reviewed_text_from_job_request
from app.services.expertgranskning.word_review import (
    _document_brief,
    accepted_review_questions,
    build_batches,
    is_heading_1_to_3,
    rewrite_suggestion_or_none,
    selected_review_questions,
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
        if line.startswith("[") and "]" in line and line[1:2].isdigit()
    ]


def _question_ids_from_user(user: str) -> list[str]:
    marker = "Moderatorfrågor"
    if marker not in user:
        marker = "Moderator questions"
    chunk = user.split(marker, 1)[-1]
    return [
        line.split("]", 1)[0].lstrip("[")
        for line in chunk.splitlines()
        if line.startswith("[") and "]" in line
    ]


def _moderation_for_batch(
    user: str,
    *,
    needs_review: bool = True,
    reason: str = "Batchen kräver bedömning.",
) -> WordBatchModeration:
    indexes = _batch_indexes_from_user(user)
    if not needs_review:
        return WordBatchModeration(
            needs_review=False,
            reason=reason,
            questions=[],
        )
    return WordBatchModeration(
        needs_review=True,
        reason=reason,
        questions=[
            WordReviewQuestion(
                id=f"q{offset}",
                paragraph_indexes=[index],
                question=f"Är stycke {index} tillräckligt tydligt?",
                why_it_matters="Otydlighet kan skapa tolkningsrisk.",
            )
            for offset, index in enumerate(indexes, start=1)
        ],
    )


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


_OBS_FIELD_KEYS = {
    "expert_id",
    "expert_namn",
    "question_id",
    "paragraph_index",
    "list_string",
    "paragraph_text",
    "kommentar",
}


def _obs(**overrides) -> WordObservation:
    values = {
        "observation_id": "o1",
        "expert_id": "frank",
        "expert_label": "Frank",
        "question_id": "q1",
        "paragraph_index": 3,
        "paragraph_text": "Konsulten försöker i möjligaste mån leverera i tid.",
        "list_string": "4.1.",
        "kommentar": "Formuleringen försöker i möjligaste mån är för svag.",
    }
    values.update(overrides)
    return WordObservation(**values)


def _passthrough_comment_convergence(user: str) -> WordCommentConvergence:
    issues: list[WordConvergedIssue] = []
    for block in user.split("### ")[1:]:
        lines = block.splitlines()
        observation_id = lines[0].strip()
        fields: dict[str, str] = {}
        current = ""
        for line in lines[1:]:
            if ": " in line:
                key, value = line.split(": ", 1)
                if key in _OBS_FIELD_KEYS:
                    current = key
                    fields[current] = value
                    continue
            if current:
                fields[current] += "\n" + line
        if not observation_id or "paragraph_index" not in fields:
            continue
        issues.append(
            WordConvergedIssue(
                observation_ids=[observation_id],
                paragraph_index=int(fields["paragraph_index"]),
                supporting_expert_ids=[fields.get("expert_id", "")],
                kommentar=fields.get("kommentar", ""),
            )
        )
    return WordCommentConvergence(issues=issues)


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


def test_accepted_review_questions_skips_trivial_and_invalid():
    batch = [_para(1, "Detta är ett giltigt stycke att granska.")]
    skipped = accepted_review_questions(
        WordBatchModeration(
            needs_review=False,
            reason="Endast kontaktuppgifter.",
            questions=[
                WordReviewQuestion(
                    id="q1",
                    paragraph_indexes=[1],
                    question="Ska inte användas.",
                )
            ],
        ),
        batch,
    )
    assert skipped == []

    kept = accepted_review_questions(
        WordBatchModeration(
            needs_review=True,
            reason="Villkor.",
            questions=[
                WordReviewQuestion(
                    id="q1",
                    paragraph_indexes=[1, 99],
                    question="Är tidsfristen tydlig?",
                    why_it_matters="Tolkningsrisk.",
                ),
                WordReviewQuestion(id="", paragraph_indexes=[1], question="Tomt id."),
                WordReviewQuestion(id="q2", paragraph_indexes=[99], question="Utom batch."),
                WordReviewQuestion(id="q1", paragraph_indexes=[1], question="Dublett."),
                WordReviewQuestion(id="q3", paragraph_indexes=[1], question="   "),
            ],
        ),
        batch,
    )
    assert [question.id for question in kept] == ["q1"]
    assert kept[0].paragraph_indexes == [1]


def test_selected_review_questions_ignores_unknown_and_duplicates():
    questions = [
        WordReviewQuestion(id="q1", paragraph_indexes=[1], question="En?"),
        WordReviewQuestion(id="q2", paragraph_indexes=[2], question="Två?"),
    ]
    assert selected_review_questions([], questions, expert_id="e1") == []
    kept = selected_review_questions(
        ["q2", "missing", "q2", "q1"],
        questions,
        expert_id="e1",
    )
    assert [question.id for question in kept] == ["q2", "q1"]


def test_intra_expert_duplicate_collapses_to_one_anchor():
    first = _obs(
        observation_id="o1",
        paragraph_index=4,
        paragraph_text="Tidsallokering regleras i detta avsnitt.",
        list_string="5.",
        kommentar="Tidsallokeringen är otydlig och bör preciseras.",
    )
    second = _obs(
        observation_id="o2",
        paragraph_index=5,
        paragraph_text="Konsulten ska lägga minst trettio timmar per vecka.",
        list_string="5.1.",
        kommentar="Tidsallokeringen är otydlig och bör preciseras i timmar.",
    )
    collapsed = collapse_intra_expert_duplicates([first, second])
    assert len(collapsed) == 1
    assert collapsed[0].paragraph_index == 5
    assert collapsed[0].list_string == "5.1."


def test_nearby_anchor_duplicate_keeps_the_specific_clause_line():
    intro = _obs(
        observation_id="o1",
        question_id="q-intro",
        paragraph_index=8,
        paragraph_text="Ersättare och överlämning.",
        list_string="6.",
        kommentar="Överlämning vid sjukdom saknar konkret rutin.",
    )
    clause = _obs(
        observation_id="o2",
        question_id="q-clause",
        paragraph_index=9,
        paragraph_text="Vid sjukdom ska konsulten utse ersättare.",
        list_string="6.1.",
        kommentar="Överlämning vid sjukdom saknar konkret rutin och tidskrav.",
    )
    collapsed = collapse_intra_expert_duplicates([intro, clause])
    assert [item.paragraph_index for item in collapsed] == [9]
    assert choose_specific_anchor([intro, clause]).paragraph_index == 9


def test_inter_expert_convergence_keeps_supporting_experts():
    observations = [
        _obs(
            observation_id="o1",
            expert_id="frank",
            expert_label="Frank",
            kommentar="Försöker i möjligaste mån är för svagt.",
        ),
        _obs(
            observation_id="o2",
            expert_id="roger",
            expert_label="Roger",
            kommentar="Best-effort-formuleringen ger motparten ett slapphetsutrymme.",
        ),
        _obs(
            observation_id="o3",
            expert_id="nils",
            expert_label="Nils",
            kommentar="Formuleringen försöker i möjligaste mån bör skärpas.",
        ),
        _obs(
            observation_id="o4",
            expert_id="daniel",
            expert_label="Daniel",
            kommentar="Åtagandet är för vagt när det bara heter i möjligaste mån.",
        ),
    ]
    parsed = WordCommentConvergence(
        issues=[
            WordConvergedIssue(
                observation_ids=["o1", "o2", "o3", "o4"],
                paragraph_index=3,
                supporting_expert_ids=["frank", "roger", "nils", "daniel"],
                kommentar=(
                    "Flera experter: 'försöker i möjligaste mån' är för svagt "
                    "och bör ersättas med ett konkret åtagande."
                ),
            )
        ]
    )
    comments = apply_word_comment_convergence(observations, parsed)
    assert len(comments) == 1
    assert comments[0].supporting_expert_ids == ("frank", "roger", "nils", "daniel")
    assert comments[0].expert_namn == "Frank, Roger, Nils, Daniel"
    assert comments[0].paragraph_index == 3
    assert "försöker i möjligaste mån" in comments[0].kommentar
    assert comments[0].kommentar.count("försöker i möjligaste mån") == 1


def test_supporting_experts_keep_all_grouped_members():
    observations = [
        _obs(observation_id="o1", expert_id="frank", expert_label="Frank"),
        _obs(observation_id="o2", expert_id="roger", expert_label="Roger"),
        _obs(observation_id="o3", expert_id="nils", expert_label="Nils"),
        _obs(observation_id="o4", expert_id="daniel", expert_label="Daniel"),
    ]
    parsed = WordCommentConvergence(
        issues=[
            WordConvergedIssue(
                observation_ids=["o1", "o2", "o3", "o4"],
                paragraph_index=3,
                supporting_expert_ids=["frank"],
                kommentar="Flera experter ser samma kärnrisk i formuleringen.",
            )
        ]
    )
    comments = apply_word_comment_convergence(observations, parsed)
    assert len(comments) == 1
    assert comments[0].supporting_expert_ids == ("frank", "roger", "nils", "daniel")
    assert comments[0].supporting_expert_labels == ("Frank", "Roger", "Nils", "Daniel")
    assert comments[0].expert_namn == "Frank, Roger, Nils, Daniel"


def test_negated_reject_preserves_dissensus():
    accept = "Räntan är inte för hög och kan godtas."
    reject = "Räntan är för hög och bör sänkas."
    assert comments_dissent([accept, reject])
    parsed = WordCommentConvergence(
        issues=[
            WordConvergedIssue(
                observation_ids=["o1", "o2"],
                paragraph_index=12,
                supporting_expert_ids=["roger", "daniel"],
                kommentar="Dröjsmålsräntan är acceptabel.",
                has_dissensus=False,
            )
        ]
    )
    comments = apply_word_comment_convergence(
        [
            _obs(
                observation_id="o1",
                expert_id="roger",
                expert_label="Roger",
                kommentar=accept,
            ),
            _obs(
                observation_id="o2",
                expert_id="daniel",
                expert_label="Daniel",
                kommentar=reject,
            ),
        ],
        parsed,
    )
    assert len(comments) == 2
    texts = {item.kommentar for item in comments}
    assert accept in texts
    assert reject in texts


def test_preserved_dissensus_is_not_merged_away():
    roger = _obs(
        observation_id="o1",
        expert_id="roger",
        expert_label="Roger",
        paragraph_index=12,
        paragraph_text="Dröjsmålsränta är referensräntan plus 15 procentenheter.",
        kommentar=(
            "Dröjsmålsräntan plus 15 procentenheter är i huvudsak acceptabel "
            "och behöver inte ändras."
        ),
    )
    nils = _obs(
        observation_id="o2",
        expert_id="nils",
        expert_label="Nils",
        paragraph_index=12,
        paragraph_text="Dröjsmålsränta är referensräntan plus 15 procentenheter.",
        kommentar="Plus 15 procentenheter är godtagbart i det här avtalet.",
    )
    daniel = _obs(
        observation_id="o3",
        expert_id="daniel",
        expert_label="Daniel",
        paragraph_index=12,
        paragraph_text="Dröjsmålsränta är referensräntan plus 15 procentenheter.",
        kommentar=(
            "Plus 15 procentenheter är för högt. Jag rekommenderar att den sänks."
        ),
    )
    assert comments_dissent([roger.kommentar, daniel.kommentar])
    assert comments_dissent(["Räntan är oacceptabel.", "Räntan är acceptabel."])
    assert not comments_dissent(
        [
            "Villkoret är orimligt vagt men kan ändå användas.",
            "Samma observation om oklar tidsallokering.",
        ]
    )
    parsed = WordCommentConvergence(
        issues=[
            WordConvergedIssue(
                observation_ids=["o1", "o2", "o3"],
                paragraph_index=12,
                supporting_expert_ids=["roger", "nils", "daniel"],
                kommentar="Dröjsmålsräntan är acceptabel.",
                has_dissensus=False,
            )
        ]
    )
    comments = apply_word_comment_convergence([roger, nils, daniel], parsed)
    assert len(comments) == 3
    by_expert = {item.expert_id: item.kommentar for item in comments}
    assert "acceptabel" in by_expert["roger"]
    assert "godtagbart" in by_expert["nils"]
    assert "sänks" in by_expert["daniel"]


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
        if response_model is WordBatchModeration:
            calls.append("moderate")
            return _moderation_for_batch(user)
        if response_model is WordExpertRaiseHand:
            calls.append("raise")
            return WordExpertRaiseHand(question_ids=_question_ids_from_user(user)[:1])
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
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
    assert calls.count("moderate") == 1
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
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=[])
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
        if "Moderatorfrågor" in messages[-1]["content"]
        or "Moderator questions" in messages[-1]["content"]
    ]
    assert raise_payloads
    moderate_payloads = [
        messages
        for messages in captured
        if "needs_review" in messages[-1]["content"]
    ]
    assert moderate_payloads
    heading_line = "[0] Heading 1 Avtal"
    body_line = "[1] Detta stycke är tillräckligt långt för granskning."
    for messages in raise_payloads + moderate_payloads:
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
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=[])
        if response_model is WordExpertComment:
            comment_calls += 1
            return WordExpertComment(kommentar="borde inte köras")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["missing-q"])
        if response_model is WordExpertComment:
            comment_calls += 1
            return WordExpertComment(kommentar="fel ankare")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
async def test_word_review_trivial_batch_skips_experts(client: AsyncClient):
    calls: list[str] = []

    async def completer(messages, response_model):
        if response_model is WordBatchModeration:
            calls.append("moderate")
            return WordBatchModeration(
                needs_review=False,
                reason="Endast kontaktuppgifter/administrativ information.",
                questions=[],
            )
        if response_model is WordExpertRaiseHand:
            calls.append("raise")
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            calls.append("comment")
            return WordExpertComment(kommentar="borde inte köras")
        if response_model is WordHeadingAssessment:
            calls.append("heading")
            return WordHeadingAssessment(forslag=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Kontakt: Anna Andersson, 070-123 45 67.")],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    assert calls == ["moderate", "heading"]
    assert [row for row in rows if not row["is_heading_suggestion"]] == []


@pytest.mark.asyncio
async def test_word_review_experts_select_subset_of_questions(client: AsyncClient):
    comment_questions: list[str] = []

    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="Villkor och tidsfrister.",
                questions=[
                    WordReviewQuestion(
                        id="q1",
                        paragraph_indexes=[1],
                        question="Är tidsfristen tydligt definierad?",
                        why_it_matters="Tolkningsrisk.",
                    ),
                    WordReviewQuestion(
                        id="q2",
                        paragraph_indexes=[2],
                        question="Är ansvarsfördelningen genomförbar?",
                        why_it_matters="Genomföranderisk.",
                    ),
                ],
            )
        if response_model is WordExpertRaiseHand:
            label = _identity_label(messages)
            if label == DEFAULT_EXPERT_LABELS[0]:
                return WordExpertRaiseHand(question_ids=["q1", "q2"])
            if label == DEFAULT_EXPERT_LABELS[1]:
                return WordExpertRaiseHand(question_ids=["q2"])
            return WordExpertRaiseHand(question_ids=[])
        if response_model is WordExpertComment:
            comment_questions.append(user)
            if "Är tidsfristen tydligt definierad?" in user:
                return WordExpertComment(kommentar="Tidsfristen är för vag.")
            return WordExpertComment(kommentar="Ansvaret är ensidigt och opraktiskt.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text=None, motivering=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[
                _para(1, "Leverans ska ske inom skälig tid efter beställning."),
                _para(2, "Leverantören ansvarar ensamt för följderna av försening."),
            ],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    comments = [
        row
        for row in rows
        if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]
    ]
    assert len(comments) == 3
    assert {(row["expert_namn"], row["paragraph_index"]) for row in comments} == {
        (DEFAULT_EXPERT_LABELS[0], 1),
        (DEFAULT_EXPERT_LABELS[0], 2),
        (DEFAULT_EXPERT_LABELS[1], 2),
    }
    assert any("Är tidsfristen tydligt definierad?" in text for text in comment_questions)
    assert any("Varför det spelar roll: Tolkningsrisk." in text for text in comment_questions)
    assert any("Är ansvarsfördelningen genomförbar?" in text for text in comment_questions)


@pytest.mark.asyncio
async def test_word_review_question_can_span_paragraphs(client: AsyncClient):
    async def completer(messages, response_model):
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="Samma villkor över två stycken.",
                questions=[
                    WordReviewQuestion(
                        id="q1",
                        paragraph_indexes=[1, 2],
                        question="Hänger tidsfrist och påföljd ihop?",
                        why_it_matters="Motsägelse mellan styckena.",
                    )
                ],
            )
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Tidsfrist och påföljd behöver samordnas.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(
                ny_text="Ny samordnad formulering.",
                motivering="Båda vill samma sak.",
            )
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[
                _para(1, "Leverans ska ske inom skälig tid efter beställning."),
                _para(2, "Vid försening utgår vite om tiotusen kronor per dag."),
            ],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    comments = [
        row
        for row in rows
        if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]
    ]
    rewrites = [row for row in rows if row["is_rewrite_suggestion"]]
    assert {(row["expert_namn"], row["paragraph_index"]) for row in comments} == {
        (DEFAULT_EXPERT_LABELS[0], 2),
        (DEFAULT_EXPERT_LABELS[1], 2),
    }
    assert {row["paragraph_index"] for row in rewrites} == {1, 2}


@pytest.mark.asyncio
async def test_word_review_empty_comment_is_not_written(client: AsyncClient):
    async def completer(messages, response_model):
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=_question_ids_from_user(messages[-1]["content"]))
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="   ")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(
                question_ids=_question_ids_from_user(messages[-1]["content"])[:1]
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
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            if label == DEFAULT_EXPERT_LABELS[0]:
                return WordExpertRaiseHand(question_ids=["q1"])
            return WordExpertRaiseHand(question_ids=[])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Bara en röst.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            rewrite_calls += 1
            return WordRewriteSuggestion(ny_text="Ska inte ske.", motivering="x")
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar=f"Olika syn från {_identity_label(messages)}.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text=None, motivering=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Skriv om till tydligare mening.")
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            assert "Kommentarer:" in user or "Comments:" in user
            return WordRewriteSuggestion(
                ny_text="Parterna ska utse kontaktpersoner.",
                motivering="Båda vill samma sak.",
            )
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
async def test_word_review_intra_expert_duplicate_writes_one_comment(
    client: AsyncClient,
):
    async def completer(messages, response_model):
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="Samma issue över två stycken.",
                questions=[
                    WordReviewQuestion(
                        id="q1",
                        paragraph_indexes=[1, 2],
                        question="Är tidsallokeringen tillräckligt konkret?",
                        why_it_matters="Tolkningsrisk.",
                    )
                ],
            )
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            return WordExpertComment(
                kommentar="Tidsallokeringen är otydlig och bör preciseras."
            )
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client, n=1)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[
                _para(1, "Tidsallokering för uppdraget regleras här.", list_string="5."),
                _para(
                    2,
                    "Konsulten ska lägga minst trettio timmar per vecka.",
                    list_string="5.1.",
                ),
            ],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    comments = [
        row
        for row in rows
        if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]
    ]
    assert len(comments) == 1
    assert comments[0]["paragraph_index"] == 2
    assert comments[0]["expert_namn"] == DEFAULT_EXPERT_LABELS[0]


@pytest.mark.asyncio
async def test_word_review_nearby_anchor_duplicate_writes_one_comment(
    client: AsyncClient,
):
    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="Närliggande stycken om samma klausul.",
                questions=[
                    WordReviewQuestion(
                        id="q1",
                        paragraph_indexes=[1],
                        question="Vad betyder ingressen om ersättare?",
                        why_it_matters="Samma klausul.",
                    ),
                    WordReviewQuestion(
                        id="q2",
                        paragraph_indexes=[2],
                        question="Hur ska överlämning ske?",
                        why_it_matters="Samma klausul.",
                    ),
                ],
            )
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1", "q2"])
        if response_model is WordExpertComment:
            return WordExpertComment(
                kommentar="Överlämning vid sjukdom saknar konkret rutin."
            )
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(user)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client, n=1)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[
                _para(1, "Ersättare och överlämning regleras nedan.", list_string="6."),
                _para(
                    2,
                    "Vid sjukdom ska konsulten utse en ersättare utan dröjsmål.",
                    list_string="6.1.",
                ),
            ],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    comments = [
        row
        for row in rows
        if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]
    ]
    assert len(comments) == 1
    assert comments[0]["paragraph_index"] == 2


@pytest.mark.asyncio
async def test_word_review_cross_batch_nearby_duplicate_writes_one_comment(
    client: AsyncClient,
):
    boundary_comment = "Tidsallokeringen är otydlig och bör preciseras."
    paragraphs = [
        _para(1, "Detta första stycke handlar om parterna i avtalet."),
        _para(2, "Detta andra stycke beskriver bakgrunden till uppdraget."),
        _para(3, "Detta tredje stycke nämner bara kontaktvägar internt."),
        _para(4, "Tidsallokering för uppdraget regleras i ingressen."),
        _para(5, "Konsulten ska lägga minst trettio timmar per vecka."),
    ]
    assert [[p.index for p in batch] for batch in build_batches(
        WordDocumentSection(
            heading="Avtal",
            heading_style="Heading 1",
            heading_paragraph_index=0,
            paragraphs=paragraphs,
        )
    )] == [[1, 2, 3, 4], [5]]

    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if response_model is WordBatchModeration:
            return _moderation_for_batch(user)
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(
                question_ids=_question_ids_from_user(user)
            )
        if response_model is WordExpertComment:
            if (
                "Tidsallokering för uppdraget regleras i ingressen." in user
                or "Konsulten ska lägga minst trettio timmar per vecka." in user
            ):
                return WordExpertComment(kommentar=boundary_comment)
            return WordExpertComment(kommentar="")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(user)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client, n=1)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(panel_id=panel_id, paragraphs=paragraphs),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    comments = [
        row
        for row in rows
        if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]
    ]
    assert len(comments) == 1
    assert comments[0]["paragraph_index"] == 5
    assert comments[0]["kommentar"] == boundary_comment


@pytest.mark.asyncio
async def test_word_review_inter_expert_convergence_writes_one_comment(
    client: AsyncClient,
):
    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if response_model is WordBatchModeration:
            return _moderation_for_batch(user)
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            return WordExpertComment(
                kommentar="Formuleringen försöker i möjligaste mån är för svag."
            )
        if response_model is WordCommentConvergence:
            parsed = _passthrough_comment_convergence(user)
            observation_ids = [
                observation_id
                for issue in parsed.issues
                for observation_id in issue.observation_ids
            ]
            expert_ids = [
                expert_id
                for issue in parsed.issues
                for expert_id in issue.supporting_expert_ids
            ]
            return WordCommentConvergence(
                issues=[
                    WordConvergedIssue(
                        observation_ids=observation_ids,
                        paragraph_index=max(
                            issue.paragraph_index for issue in parsed.issues
                        ),
                        supporting_expert_ids=expert_ids,
                        kommentar=(
                            "Flera experter: 'försöker i möjligaste mån' är för svagt "
                            "och bör ersättas med ett konkret åtagande."
                        ),
                    )
                ]
            )
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
            paragraphs=[
                _para(1, "Konsulten försöker i möjligaste mån leverera i tid.")
            ],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    comments = [
        row
        for row in rows
        if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]
    ]
    assert len(comments) == 1
    assert DEFAULT_EXPERT_LABELS[0] in comments[0]["expert_namn"]
    assert DEFAULT_EXPERT_LABELS[1] in comments[0]["expert_namn"]
    assert comments[0]["kommentar"].count("försöker i möjligaste mån") == 1


@pytest.mark.asyncio
async def test_word_review_preserves_dissensus_as_separate_comments(
    client: AsyncClient,
):
    async def completer(messages, response_model):
        label = _identity_label(messages)
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            if label == DEFAULT_EXPERT_LABELS[0]:
                return WordExpertComment(
                    kommentar=(
                        "Dröjsmålsräntan plus 15 procentenheter är i huvudsak "
                        "acceptabel och behöver inte ändras."
                    )
                )
            return WordExpertComment(
                kommentar=(
                    "Plus 15 procentenheter är för högt. Jag rekommenderar att den sänks."
                )
            )
        if response_model is WordCommentConvergence:
            parsed = _passthrough_comment_convergence(messages[-1]["content"])
            return WordCommentConvergence(
                issues=[
                    WordConvergedIssue(
                        observation_ids=[
                            oid for issue in parsed.issues for oid in issue.observation_ids
                        ],
                        paragraph_index=1,
                        supporting_expert_ids=[
                            expert_id
                            for issue in parsed.issues
                            for expert_id in issue.supporting_expert_ids
                        ],
                        kommentar="Dröjsmålsräntan är acceptabel.",
                        has_dissensus=False,
                    )
                ]
            )
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
            paragraphs=[
                _para(
                    1,
                    "Vid dröjsmål utgår ränta med referensräntan plus 15 procentenheter.",
                )
            ],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    comments = [
        row
        for row in rows
        if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]
    ]
    assert len(comments) == 2
    texts = " ".join(row["kommentar"] for row in comments)
    assert "acceptabel" in texts
    assert "sänks" in texts


@pytest.mark.asyncio
async def test_word_review_patch_comment_id(client: AsyncClient):
    async def completer(messages, response_model):
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="ok")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text=None, motivering=None)
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(messages[-1]["content"])
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
