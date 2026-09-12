"""Expertgranskning Word review: list_string, batches, raise-hand, rewrite."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import select

from app.database.models import ExpertgranskningResult, Job, PanelSession
from app.realtime.expertgranskning_broadcast import expertgranskning_broadcast
from pydantic import ValidationError

from app.llm import set_structured_completer
from app.services import jobs as jobs_service
from app.services.expertgranskning import WORD_JOB_KIND
from app.services.expertgranskning.comment_convergence import (
    COMMENT_CONVERGENCE_CHUNK_HARD_CAP,
    COMMENT_CONVERGENCE_CHUNK_SIZE,
    WordObservation,
    apply_word_comment_convergence,
    choose_specific_anchor,
    chunk_observations_for_convergence,
    collapse_intra_expert_duplicates,
    comments_dissent,
    decide_word_issue_materialization,
    paragraph_indexes_for_observations,
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
from app.services.word.anchors import reviewed_text_from_job_request
from app.services.expertgranskning.word_review import (
    WORD_COMMENT_CONVERGENCE_SUFFIX,
    _comment_convergence,
    _comment_question,
    _consolidate_comments,
    _document_brief,
    accepted_review_questions,
    build_batches,
    is_heading_1_to_3,
    render_comment_convergence_user_prompt,
    render_expert_comment_user_prompt,
    resolve_comment_anchor,
    rewrite_suggestion_or_none,
    selected_review_questions,
    should_review_paragraph,
    word_comment_anchor_suffix,
    word_paragraph_review,
)
from app.services.expertgranskning.word_review_timing import (
    WordReviewLimiter,
    WordReviewTimings,
)
from app.services.panel.schemas import PanelExpertSlot
from app.services.expertgranskning.word_structured import (
    complete_word_structured,
    is_json_syntax_validation_error,
    validation_category,
)
from app.services.prompt_catalog import default_prompts, render_prompt
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


def _review_task(panel_id: int = 1, *, paragraph_indexes: list[int] | None = None) -> dict:
    if paragraph_indexes is None:
        scope: dict = {"type": "document"}
    else:
        scope = {"type": "selection", "paragraph_indexes": paragraph_indexes}
    return {
        "task_type": "review",
        "scope": scope,
        "expert_strategy": {"type": "panel", "panel_id": panel_id},
    }


def _payload(*, heading="Avtal", paragraphs: list[WordDocumentParagraph], **extra):
    panel_id = extra.get("panel_id", 1)
    body = {
        "task": extra.get("task") or _review_task(
            panel_id,
            paragraph_indexes=extra.get("selection"),
        ),
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
    if "review_intent" in extra:
        body["review_intent"] = extra["review_intent"]
    if "intent_interview" in extra:
        body["intent_interview"] = extra["intent_interview"]
    if "intent_answers" in extra:
        body["intent_answers"] = extra["intent_answers"]
    return body


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


def _issue(**overrides) -> WordConvergedIssue:
    values = {
        "observation_ids": ["o1"],
        "paragraph_index": 3,
        "supporting_expert_ids": ["frank"],
        "short_comment": "Skärp formuleringen.",
        "explanation": "Formuleringen saknar ett konkret åtagande.",
        "materiality": "high",
        "actionability": "actionable",
        "novelty": "new",
        "should_materialize": True,
        "has_dissensus": False,
    }
    values.update(overrides)
    return WordConvergedIssue(**values)


def _passthrough_comment_convergence(user: str) -> WordCommentConvergence:
    issues: list[WordConvergedIssue] = []
    for block in user.split("### ")[1:]:
        lines = block.splitlines()
        observation_id = lines[0].strip()
        fields: dict[str, str] = {}
        current = ""
        for line in lines[1:]:
            if (
                line.startswith("Returnera ")
                or line.startswith("Return issues ")
                or line.startswith("Output contract:")
            ):
                break
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
            _issue(
                observation_ids=[observation_id],
                paragraph_index=int(fields["paragraph_index"]),
                supporting_expert_ids=[fields.get("expert_id", "")],
                short_comment=fields.get("kommentar", ""),
                explanation="",
            )
        )
    return WordCommentConvergence(issues=issues)


def test_list_string_defaults_empty_for_legacy_clients():
    para = WordDocumentParagraph(index=3, text="Brödtext", style="Normal")
    assert para.list_string == ""


def test_document_brief_indexes_match_paragraph_index():
    payload = ExpertgranskningWordJobRequest.model_validate(
        {
            "task": _review_task(),
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
            "task": _review_task(),
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

    scoped = accepted_review_questions(
        WordBatchModeration(
            needs_review=True,
            reason="Villkor.",
            questions=[
                WordReviewQuestion(
                    id="q1",
                    paragraph_indexes=[1, 2],
                    question="Bara det valda stycket.",
                )
            ],
        ),
        [_para(1, "Valt stycke att granska här."), _para(2, "Inte valt men i batchen.")],
        target_indexes=frozenset({1}),
    )
    assert scoped[0].paragraph_indexes == [1]


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
            _issue(
                observation_ids=["o1", "o2", "o3", "o4"],
                paragraph_index=3,
                supporting_expert_ids=["frank", "roger", "nils", "daniel"],
                short_comment=(
                    "Flera experter: 'försöker i möjligaste mån' är för svagt "
                    "och bör ersättas med ett konkret åtagande."
                ),
                explanation=(
                    "Best-effort-formuleringen ger motparten ett slapphetsutrymme "
                    "och bör bytas mot ett mätbart åtagande."
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
    assert "slapphetsutrymme" in comments[0].explanation
    assert comments[0].should_materialize is True


def test_supporting_experts_keep_all_grouped_members():
    observations = [
        _obs(observation_id="o1", expert_id="frank", expert_label="Frank"),
        _obs(observation_id="o2", expert_id="roger", expert_label="Roger"),
        _obs(observation_id="o3", expert_id="nils", expert_label="Nils"),
        _obs(observation_id="o4", expert_id="daniel", expert_label="Daniel"),
    ]
    parsed = WordCommentConvergence(
        issues=[
            _issue(
                observation_ids=["o1", "o2", "o3", "o4"],
                paragraph_index=3,
                supporting_expert_ids=["frank"],
                short_comment="Flera experter ser samma kärnrisk i formuleringen.",
            )
        ]
    )
    comments = apply_word_comment_convergence(observations, parsed)
    assert len(comments) == 1
    assert comments[0].supporting_expert_ids == ("frank", "roger", "nils", "daniel")
    assert comments[0].supporting_expert_labels == ("Frank", "Roger", "Nils", "Daniel")
    assert comments[0].expert_namn == "Frank, Roger, Nils, Daniel"


def test_convergence_cannot_invent_unrelated_paragraph():
    observations = [
        _obs(observation_id="o1", paragraph_index=1, list_string="8."),
        _obs(observation_id="o2", paragraph_index=2, list_string="8.1."),
    ]
    parsed = WordCommentConvergence(
        issues=[
            _issue(
                observation_ids=["o1", "o2"],
                paragraph_index=99,
                supporting_expert_ids=["frank"],
                short_comment="Ska stanna på de grupperade ankaren.",
            )
        ]
    )
    comments = apply_word_comment_convergence(observations, parsed)
    assert len(comments) == 1
    assert comments[0].paragraph_index == 2
    assert comments[0].paragraph_index != 99


def test_negated_reject_preserves_dissensus():
    accept = "Räntan är inte för hög och kan godtas."
    reject = "Räntan är för hög och bör sänkas."
    assert comments_dissent([accept, reject])
    parsed = WordCommentConvergence(
        issues=[
            _issue(
                observation_ids=["o1", "o2"],
                paragraph_index=12,
                supporting_expert_ids=["roger", "daniel"],
                short_comment="Dröjsmålsräntan är acceptabel.",
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
            _issue(
                observation_ids=["o1", "o2", "o3"],
                paragraph_index=12,
                supporting_expert_ids=["roger", "nils", "daniel"],
                short_comment="Dröjsmålsräntan är acceptabel.",
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
    assert all(item.should_materialize for item in comments)
    assert all(item.has_dissensus for item in comments)


def test_converged_issue_keeps_short_comment_and_explanation_apart():
    parsed = WordCommentConvergence(
        issues=[
            _issue(
                observation_ids=["o1"],
                short_comment="Byt till ett konkret leveransåtagande.",
                explanation=(
                    "Formuleringen 'försöker i möjligaste mån' lämnar motparten "
                    "utan mätbart krav och bör skärpas."
                ),
            )
        ]
    )
    comments = apply_word_comment_convergence([_obs()], parsed)
    assert len(comments) == 1
    assert comments[0].kommentar == "Byt till ett konkret leveransåtagande."
    assert "mätbart krav" in comments[0].explanation
    assert comments[0].kommentar not in comments[0].explanation
    assert comments[0].should_materialize is True


def test_word_issue_schema_fails_closed_without_judgment_fields():
    with pytest.raises(ValidationError):
        WordConvergedIssue(
            observation_ids=["o1"],
            paragraph_index=3,
            supporting_expert_ids=["frank"],
            short_comment="En kort kommentar.",
            explanation="En längre motivering.",
        )
    with pytest.raises(ValidationError):
        WordConvergedIssue.model_validate(
            {
                "observation_ids": ["o1"],
                "paragraph_index": 3,
                "supporting_expert_ids": ["frank"],
                "short_comment": "En kort kommentar.",
                "explanation": "En längre motivering.",
                "materiality": "critical",
                "actionability": "actionable",
                "novelty": "new",
                "should_materialize": True,
            }
        )


def test_low_materiality_informational_issue_is_not_materialized():
    issue = _issue(
        materiality="low",
        actionability="informational",
        should_materialize=True,
    )
    assert decide_word_issue_materialization(issue) is False
    comments = apply_word_comment_convergence([_obs()], WordCommentConvergence(issues=[issue]))
    assert comments[0].should_materialize is False


def test_overlapping_issue_is_not_materialized():
    first = _obs(observation_id="o1", expert_id="frank", expert_label="Frank")
    second = _obs(observation_id="o2", expert_id="roger", expert_label="Roger")
    parsed = WordCommentConvergence(
        issues=[
            _issue(
                observation_ids=["o1"],
                short_comment="Skärp leveransåtagandet.",
                explanation="Best-effort lämnar ett slapphetsutrymme.",
            ),
            _issue(
                observation_ids=["o2"],
                supporting_expert_ids=["roger"],
                short_comment="Samma best-effort-problem igen.",
                explanation="Redan täckt av den första issuen.",
                novelty="overlap",
                should_materialize=True,
            ),
        ]
    )
    comments = apply_word_comment_convergence([first, second], parsed)
    assert [item.should_materialize for item in comments] == [True, False]


def test_dissensus_is_not_filtered_as_overlap():
    issue = _issue(
        novelty="overlap",
        should_materialize=False,
        has_dissensus=True,
    )
    assert decide_word_issue_materialization(issue) is True


def test_leftover_observation_still_materializes():
    kept = _obs(observation_id="o1")
    leftover = _obs(
        observation_id="o2",
        expert_id="roger",
        expert_label="Roger",
        kommentar="En annan genuin risk i samma stycke.",
    )
    parsed = WordCommentConvergence(
        issues=[
            _issue(
                observation_ids=["o1"],
                short_comment="Skärp leveransåtagandet.",
            )
        ]
    )
    comments = apply_word_comment_convergence([kept, leftover], parsed)
    assert len(comments) == 2
    by_expert = {item.expert_id: item for item in comments}
    assert by_expert["roger"].kommentar == leftover.kommentar
    assert by_expert["roger"].should_materialize is True


def test_intent_is_used_when_deciding_materialization():
    relevant = _issue(
        short_comment="Förtydliga betalningsfristen.",
        should_materialize=True,
    )
    off_purpose = _issue(
        observation_ids=["o2"],
        supporting_expert_ids=["roger"],
        short_comment="Justera ett kosmetiskt komma.",
        materiality="low",
        actionability="informational",
        should_materialize=False,
    )
    assert decide_word_issue_materialization(relevant) is True
    assert decide_word_issue_materialization(off_purpose) is False


def test_comment_convergence_chunks_keep_nearby_paragraphs_together():
    spread = [
        _obs(observation_id=f"o{index}", paragraph_index=index * 3)
        for index in range(1, 16)
    ]
    chunks = chunk_observations_for_convergence(spread)
    assert COMMENT_CONVERGENCE_CHUNK_SIZE == 12
    assert [len(chunk) for chunk in chunks] == [12, 3]
    assert [item.observation_id for chunk in chunks for item in chunk] == [
        item.observation_id for item in spread
    ]
    nearby = [
        _obs(
            observation_id=f"n{index}",
            paragraph_index=10 + index,
            expert_id=f"e{index}",
        )
        for index in range(13)
    ]
    overflow = chunk_observations_for_convergence(nearby)
    assert len(overflow) == 1
    assert len(overflow[0]) == 13
    assert COMMENT_CONVERGENCE_CHUNK_HARD_CAP == 24
    packed = [
        *_obs_range(start=1, count=5),
        *_obs_range(start=20, count=5),
        *_obs_range(start=40, count=5),
    ]
    packed_chunks = chunk_observations_for_convergence(packed)
    assert [len(chunk) for chunk in packed_chunks] == [10, 5]
    assert paragraph_indexes_for_observations(packed_chunks[0]) == set(range(1, 6)) | set(
        range(20, 25)
    )
    assert paragraph_indexes_for_observations(packed_chunks[1]) == set(range(40, 45))


def test_comment_convergence_splits_contiguous_cluster_at_hard_cap():
    contiguous = [
        _obs(
            observation_id=f"c{index:02d}",
            paragraph_index=index,
            expert_id=f"e{index}",
        )
        for index in range(1, 31)
    ]
    shuffled = list(reversed(contiguous))
    chunks = chunk_observations_for_convergence(shuffled)
    sizes = [len(chunk) for chunk in chunks]
    assert max(sizes) <= COMMENT_CONVERGENCE_CHUNK_HARD_CAP
    assert all(size <= COMMENT_CONVERGENCE_CHUNK_HARD_CAP for size in sizes)
    assert sum(sizes) == 30
    seen = [item.observation_id for chunk in chunks for item in chunk]
    assert seen == [item.observation_id for item in contiguous]
    assert len(seen) == len(set(seen))
    assert chunk_observations_for_convergence(contiguous) == chunks


def _obs_range(*, start: int, count: int) -> list[WordObservation]:
    return [
        _obs(
            observation_id=f"p{start}_{offset}",
            paragraph_index=start + offset,
            expert_id=f"e{start}_{offset}",
        )
        for offset in range(count)
    ]


def _truncated_expert_json_error() -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        WordExpertComment.model_validate_json('{"kommentar": "Immaterialrätt')
    return caught.value


def _truncated_convergence_json_error() -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        WordCommentConvergence.model_validate_json(
            '{"issues": [{"observation_ids": ["o1"], "paragraph_index": 3, "kommentar": "Avtal'
        )
    return caught.value


def test_json_syntax_error_is_detected_for_truncated_object():
    assert is_json_syntax_validation_error(_truncated_expert_json_error())
    assert is_json_syntax_validation_error(_truncated_convergence_json_error())
    with pytest.raises(ValidationError) as caught:
        WordExpertComment.model_validate({"anchor_paragraph_index": "nej"})
    assert not is_json_syntax_validation_error(caught.value)


@pytest.mark.asyncio
async def test_comment_convergence_batch_text_uses_chunk_paragraphs(monkeypatch):
    seen: list[tuple[list[int], list[str]]] = []

    async def fake_convergence(
        *,
        prompts,
        section,
        batch,
        observations,
        limiter,
        review_intent="",
    ):
        seen.append(
            (
                [paragraph.index for paragraph in batch],
                [item.observation_id for item in observations],
            )
        )
        return WordCommentConvergence(issues=[])

    monkeypatch.setattr(
        "app.services.expertgranskning.word_review._comment_convergence",
        fake_convergence,
    )
    paragraphs = [
        _para(index, f"Stycke {index} är tillräckligt långt för granskning.")
        for index in range(1, 40)
    ]
    section = WordDocumentSection(
        heading="Avtal",
        heading_style="Heading 1",
        heading_paragraph_index=0,
        paragraphs=paragraphs,
    )
    comments = []
    for index in range(1, 16):
        paragraph_index = index * 2
        slot = PanelExpertSlot(slot_id=f"e{index}", label=f"Expert {index}")
        question = WordReviewQuestion(
            id=f"q{index}",
            paragraph_indexes=[paragraph_index],
            question="Risk?",
        )
        comments.append((slot, question, f"Kommentar {index} om risken.", paragraph_index))
    written = await _consolidate_comments(
        prompts=default_prompts("sv"),
        section=section,
        paragraphs=paragraphs,
        comments=comments,
        by_index={paragraph.index: paragraph for paragraph in paragraphs},
        limiter=WordReviewLimiter(8, WordReviewTimings()),
    )
    assert len(written) == 15
    assert len(seen) == 2
    first_indexes, first_ids = seen[0]
    second_indexes, second_ids = seen[1]
    assert len(first_ids) == 12
    assert len(second_ids) == 3
    assert first_indexes == [index * 2 for index in range(1, 13)]
    assert second_indexes == [index * 2 for index in range(13, 16)]
    assert 1 not in first_indexes
    assert 38 not in first_indexes


def test_resolve_comment_anchor_uses_explicit_and_single_index():
    question = WordReviewQuestion(
        id="q1",
        paragraph_indexes=[10, 11],
        question="IP?",
    )
    assert (
        resolve_comment_anchor(
            question,
            WordExpertComment(kommentar="x", anchor_paragraph_index=10),
        )
        == 10
    )
    assert (
        resolve_comment_anchor(
            question,
            WordExpertComment(kommentar="x", anchor_paragraph_index=99),
        )
        is None
    )
    assert (
        resolve_comment_anchor(
            question,
            WordExpertComment(kommentar="x"),
        )
        is None
    )
    single = WordReviewQuestion(id="q2", paragraph_indexes=[4], question="En?")
    assert (
        resolve_comment_anchor(single, WordExpertComment(kommentar="x")) == 4
    )
    assert (
        resolve_comment_anchor(
            question,
            WordExpertComment(kommentar="x", anchor_paragraph_index=10),
            target_indexes=frozenset({11}),
        )
        is None
    )
    assert (
        resolve_comment_anchor(
            question,
            WordExpertComment.model_validate(
                {"kommentar": "x", "anchor_paragraph_index": ""}
            ),
        )
        is None
    )


def test_word_alembic_chain_is_linear_after_main_head():
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["073_word_review_issue_quality"]
    quality = script.get_revision("073_word_review_issue_quality")
    assert quality.down_revision == "072_intent_interview_trust"
    trust = script.get_revision("072_intent_interview_trust")
    assert trust.down_revision == "071_intent_interview"
    interview = script.get_revision("071_intent_interview")
    assert interview.down_revision == "070_review_intent"
    intent = script.get_revision("070_review_intent")
    assert intent.down_revision == "069_word_actions"
    actions = script.get_revision("069_word_actions")
    assert actions.down_revision == "068_word_application_lifecycle"
    lifecycle = script.get_revision("068_word_application_lifecycle")
    assert lifecycle.down_revision == "067_researchplan_valid_proposals"
    retry = script.get_revision("065_word_comment_anchor_retry")
    assert retry.down_revision == "064_word_comment_convergence"
    convergence = script.get_revision("064_word_comment_convergence")
    assert convergence.down_revision == "063_panel_competency_state"


def test_word_comment_prompt_stays_party_neutral():
    text = render_prompt(
        default_prompts("sv"),
        "expertgranskning.word.expert.comment",
        label="Jurist",
        profile="Jurist",
        paragraph_text="Kunden ska betala.",
        list_string="3.1.",
        section_heading="Avtal",
        question="Vem bär risken?",
        why_it_matters="Partsneutral läsning.",
        allowed_paragraph_indexes="3",
    )
    assert "Granskande part är okänd" in text
    assert "Leverantören" in text
    assert "Beställaren" in text
    assert "skriv inte för er som kund" in text
    assert "granskningsavsikt" in text.lower()
    synthesis = default_prompts("sv")["expertgranskning.word.comment_convergence"]
    assert "Granskande part är okänd" in synthesis
    assert "Vänd inte på dokumentfakta" in synthesis
    assert "short_comment" in synthesis
    assert "should_materialize" in synthesis
    assert "granskningsavsikt" in synthesis


_OLD_COMMENT_OVERRIDE = (
    "Din roll: {label}\n"
    "Profil: {profile}\n\n"
    "Hela dokumentet ligger i systemmeddelandet.\n\n"
    "Avsnitt: {section_heading}\n"
    "Klausulnummer (internt): {list_string}\n\n"
    "Granskningsfråga: {question}\n"
    "Varför det spelar roll: {why_it_matters}\n\n"
    "Relevant dokumenttext:\n{paragraph_text}\n\n"
    "Ge en konkret expertbedömning. Återberätta inte texten och kommentera inte "
    "enbart att information finns. Förklara vad som är relevant, problematiskt, "
    "osäkert eller bör förbättras. Tom kommentar betyder att du hoppar över. "
    "Inga tekniska termer. Prefixera inte med klausulnummer."
)


def test_old_comment_override_still_sends_server_owned_anchor_contract():
    assert "anchor_paragraph_index" not in _OLD_COMMENT_OVERRIDE
    assert "{allowed_paragraph_indexes}" not in _OLD_COMMENT_OVERRIDE
    prompts = default_prompts("sv")
    prompts["expertgranskning.word.expert.comment"] = _OLD_COMMENT_OVERRIDE
    paragraphs = [
        _para(12, "Leverantören behåller all immaterialrätt till underlaget."),
        _para(13, "Beställaren ska betala fakturan inom trettio dagar."),
    ]
    text = render_expert_comment_user_prompt(
        prompts,
        slot=PanelExpertSlot(slot_id="jur", label="Jurist", profile="Avtal"),
        section=WordDocumentSection(
            heading="Avtal",
            heading_style="Heading 1",
            heading_paragraph_index=0,
            paragraphs=paragraphs,
        ),
        question=WordReviewQuestion(
            id="q1",
            paragraph_indexes=[12, 13],
            question="Var sitter immaterialrätten?",
            why_it_matters="Fel ankare.",
        ),
        paragraphs=paragraphs,
    )
    assert "Allowed anchors: 12, 13." in text
    assert "Return exactly one anchor_paragraph_index from this set." in text
    assert word_comment_anchor_suffix([12, 13]) in text
    assert text.endswith(word_comment_anchor_suffix([12, 13]))


@pytest.mark.asyncio
async def test_comment_call_sends_anchor_contract_with_old_override():
    captured: list[str] = []

    async def completer(messages, response_model):
        captured.extend(message.get("content") or "" for message in messages)
        return WordExpertComment(
            kommentar="IP-klausulen är för vid.",
            anchor_paragraph_index=12,
        )

    set_structured_completer(completer)
    prompts = default_prompts("sv")
    prompts["expertgranskning.word.expert.comment"] = _OLD_COMMENT_OVERRIDE
    paragraphs = [
        _para(12, "Leverantören behåller all immaterialrätt till underlaget."),
        _para(13, "Beställaren ska betala fakturan inom trettio dagar."),
    ]
    slot, question, text, anchor = await _comment_question(
        prompts=prompts,
        slot=PanelExpertSlot(slot_id="jur", label="Jurist", profile="Avtal"),
        brief="[12] Leverantören behåller all immaterialrätt till underlaget.",
        section=WordDocumentSection(
            heading="Avtal",
            heading_style="Heading 1",
            heading_paragraph_index=0,
            paragraphs=paragraphs,
        ),
        question=WordReviewQuestion(
            id="q1",
            paragraph_indexes=[12, 13],
            question="Var sitter immaterialrätten?",
            why_it_matters="Fel ankare.",
        ),
        paragraphs=paragraphs,
        limiter=WordReviewLimiter(1, WordReviewTimings()),
    )
    sent = "\n".join(captured)
    assert "Allowed anchors: 12, 13." in sent
    assert "Return exactly one anchor_paragraph_index from this set." in sent
    assert "anchor_paragraph_index" not in _OLD_COMMENT_OVERRIDE
    assert text == "IP-klausulen är för vid."
    assert anchor == 12
    assert slot.slot_id == "jur"
    assert question.id == "q1"


_OLD_COMMENT_CONVERGENCE_OVERRIDE = (
    "Du konsoliderar expertkommentarer till Word-kommentarer. "
    "Deduplicera observationer/issues, inte experter.\n\n"
    "Avsnitt: {section_heading}\n\n"
    "Batch:\n{batch_text}\n\n"
    "Observationer:\n{observations}\n\n"
    "Returnera issues med observation_ids, paragraph_index, "
    "supporting_expert_ids, kommentar och has_dissensus."
)


def test_old_convergence_override_still_sends_server_owned_output_contract():
    assert "short_comment" not in _OLD_COMMENT_CONVERGENCE_OVERRIDE
    assert "should_materialize" not in _OLD_COMMENT_CONVERGENCE_OVERRIDE
    prompts = default_prompts("sv")
    prompts["expertgranskning.word.comment_convergence"] = (
        _OLD_COMMENT_CONVERGENCE_OVERRIDE
    )
    observations = [_obs()]
    section = WordDocumentSection(
        heading="Avtal",
        heading_style="Heading 1",
        heading_paragraph_index=0,
        paragraphs=[_para(3, "Konsulten försöker i möjligaste mån leverera i tid.")],
    )
    text = render_comment_convergence_user_prompt(
        prompts,
        section=section,
        batch=list(section.paragraphs),
        observations=observations,
    )
    assert "Returnera issues med observation_ids, paragraph_index, " in text
    assert "kommentar och has_dissensus." in text
    assert WORD_COMMENT_CONVERGENCE_SUFFIX in text
    assert text.endswith(WORD_COMMENT_CONVERGENCE_SUFFIX)
    assert "short_comment" in text
    assert "should_materialize" in text


@pytest.mark.asyncio
async def test_convergence_call_sends_output_contract_with_old_override():
    captured: list[str] = []

    async def completer(messages, response_model):
        captured.extend(message.get("content") or "" for message in messages)
        return WordCommentConvergence(issues=[_issue()])

    set_structured_completer(completer)
    prompts = default_prompts("sv")
    prompts["expertgranskning.word.comment_convergence"] = (
        _OLD_COMMENT_CONVERGENCE_OVERRIDE
    )
    section = WordDocumentSection(
        heading="Avtal",
        heading_style="Heading 1",
        heading_paragraph_index=0,
        paragraphs=[_para(3, "Konsulten försöker i möjligaste mån leverera i tid.")],
    )
    parsed = await _comment_convergence(
        prompts=prompts,
        section=section,
        batch=list(section.paragraphs),
        observations=[_obs()],
        limiter=WordReviewLimiter(1, WordReviewTimings()),
    )
    sent = "\n".join(captured)
    assert WORD_COMMENT_CONVERGENCE_SUFFIX in sent
    assert sent.strip().endswith(WORD_COMMENT_CONVERGENCE_SUFFIX)
    assert parsed.issues[0].short_comment == "Skärp formuleringen."


@pytest.mark.asyncio
async def test_word_structured_retries_truncated_json_once(caplog):
    calls = 0

    async def completer(messages, response_model):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _truncated_expert_json_error()
        assert any(
            "ogiltig JSON" in (message.get("content") or "")
            for message in messages
        )
        return WordExpertComment(
            kommentar="Komplett IP-bedömning.",
            anchor_paragraph_index=1,
        )

    set_structured_completer(completer)
    with caplog.at_level("INFO"):
        parsed = await complete_word_structured(
            [{"role": "user", "content": "kommentera"}],
            WordExpertComment,
            prompts=default_prompts("sv"),
        )
    assert parsed.kommentar == "Komplett IP-bedömning."
    assert calls == 2
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "schema=WordExpertComment" in logged
    assert "attempt=1" in logged
    assert "category=json_invalid" in logged
    assert "Immaterialrätt" not in logged
    assert '{"kommentar"' not in logged


@pytest.mark.asyncio
async def test_word_structured_second_json_error_propagates():
    calls = 0

    async def completer(messages, response_model):
        nonlocal calls
        calls += 1
        raise _truncated_expert_json_error()

    set_structured_completer(completer)
    with pytest.raises(ValidationError) as caught:
        await complete_word_structured(
            [{"role": "user", "content": "kommentera"}],
            WordExpertComment,
            prompts=default_prompts("sv"),
        )
    assert is_json_syntax_validation_error(caught.value)
    assert validation_category(caught.value) == "json_invalid"
    assert calls == 2


@pytest.mark.asyncio
async def test_word_structured_does_not_retry_semantic_validation():
    calls = 0

    async def completer(messages, response_model):
        nonlocal calls
        calls += 1
        WordExpertComment.model_validate({"anchor_paragraph_index": "nej"})
        raise AssertionError("should have failed")

    set_structured_completer(completer)
    with pytest.raises(ValidationError) as caught:
        await complete_word_structured(
            [{"role": "user", "content": "kommentera"}],
            WordExpertComment,
            prompts=default_prompts("sv"),
        )
    assert not is_json_syntax_validation_error(caught.value)
    assert calls == 1


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
        ExpertgranskningWordJobCreate(task=_review_task(), locale="en-US", sections=[section])
    with pytest.raises(ValidationError):
        ExpertgranskningWordJobCreate(
            task=_review_task(),
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
            task=_review_task(),
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
    result = job.json()["result"]
    assert result["paragraph_reviews"] == 1
    assert result["llm_call_count"] >= 1
    assert result["max_observed_llm_concurrency"] >= 1
    assert result["total_ms"] >= 0
    assert result["time_to_first_action_ms"] is not None
    assert job.json()["request"]["task"] == _review_task(panel_id)


@pytest.mark.asyncio
async def test_word_review_selection_scope_stays_inside_target(client: AsyncClient):
    captured: list[list[dict]] = []

    async def completer(messages, response_model):
        captured.append(messages)
        user = messages[-1]["content"]
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="Batchen kräver bedömning.",
                questions=[
                    WordReviewQuestion(
                        id="q-out",
                        paragraph_indexes=[1],
                        question="Utom markeringen?",
                    ),
                    WordReviewQuestion(
                        id="q-in",
                        paragraph_indexes=[2],
                        question="Är stycke 2 tydligt?",
                    ),
                ],
            )
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q-in", "q-out"])
        if response_model is WordExpertComment:
            return WordExpertComment(
                kommentar="Kommentar som försöker lämna markeringen.",
                anchor_paragraph_index=1,
            )
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag="Rubrik utanför markeringen")
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(
                ny_text="Omskrivning utanför markeringen.",
                motivering="Ska inte materialiseras.",
            )
        if response_model is WordCommentConvergence:
            return WordCommentConvergence(
                issues=[
                    _issue(
                        observation_ids=["o1"],
                        paragraph_index=1,
                        supporting_expert_ids=["slot_1"],
                        short_comment="Konvergens utanför markeringen.",
                    )
                ]
            )
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            selection=[2],
            paragraphs=[
                _para(1, "Detta stycke är utanför markeringen men finns i dokumentet."),
                _para(2, "Detta stycke är tillräckligt långt för granskning."),
            ],
        ),
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    stored = (await client.get(f"/jobs/{job_id}")).json()["request"]
    assert stored["task"]["scope"] == {"type": "selection", "paragraph_indexes": [2]}
    assert stored["sections"][0]["paragraphs"][0]["index"] == 1
    await jobs_service._run_job(job_id)

    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/results")
    rows = listed.json()
    assert {row["paragraph_index"] for row in rows} <= {2}
    assert not any(row["is_heading_suggestion"] for row in rows)
    actions = (await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")).json()
    assert all(action["anchor"]["paragraph_index"] == 2 for action in actions)

    batch_users = [
        messages[-1]["content"]
        for messages in captured
        if "Den här batchen" in messages[-1]["content"]
        or "This batch" in messages[-1]["content"]
    ]
    assert batch_users
    assert _batch_indexes_from_user(batch_users[0]) == [2]
    brief_systems = [
        str(message.get("content") or "")
        for messages in captured
        for message in messages
        if message.get("role") == "system"
    ]
    assert any(
        "[1] Detta stycke är utanför markeringen men finns i dokumentet." in text
        and "[2] Detta stycke är tillräckligt långt för granskning." in text
        for text in brief_systems
    )
    assert not any("Nuvarande rubrik:" in messages[-1]["content"] for messages in captured)


@pytest.mark.asyncio
async def test_word_review_selection_scope_can_comment_and_replace(client: AsyncClient):
    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if response_model is WordBatchModeration:
            return _moderation_for_batch(user)
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=_question_ids_from_user(user)[:1])
        if response_model is WordExpertComment:
            return WordExpertComment(
                kommentar="Kommentar på det valda stycket.",
                anchor_paragraph_index=2,
            )
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag="Ska inte skrivas")
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(
                ny_text="Ny formulering i markeringen.",
                motivering="Samma fix.",
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
            selection=[2],
            paragraphs=[
                _para(1, "Detta stycke är utanför markeringen men finns i dokumentet."),
                _para(2, "Detta stycke är tillräckligt långt för granskning."),
            ],
        ),
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)

    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    assert {row["paragraph_index"] for row in rows} == {2}
    assert any(row["is_rewrite_suggestion"] for row in rows)
    assert not any(row["is_heading_suggestion"] for row in rows)
    actions = (await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")).json()
    assert actions
    assert {action["action_type"] for action in actions} == {"comment", "replace"}
    assert all(action["anchor"]["paragraph_index"] == 2 for action in actions)
    assert all(action["status"] == "pending" for action in actions)


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
async def test_word_review_includes_review_intent_in_system_messages(client: AsyncClient):
    captured: list[list[dict]] = []
    intent = "Det är Devbrains som är motpart i avtalet."

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
            review_intent=intent,
        ),
    )
    assert created.status_code == 202, created.text
    await jobs_service._run_job(created.json()["job_id"])
    raise_payloads = [
        messages
        for messages in captured
        if "Moderatorfrågor" in messages[-1]["content"]
        or "Moderator questions" in messages[-1]["content"]
    ]
    moderate_payloads = [
        messages
        for messages in captured
        if "needs_review" in messages[-1]["content"]
        or "needs_review" in str(messages[-1].get("content") or "")
    ]
    heading_payloads = [
        messages
        for messages in captured
        if "Nuvarande rubrik:" in messages[-1]["content"]
        or "Current heading:" in messages[-1]["content"]
    ]
    assert raise_payloads
    assert moderate_payloads
    heading_line = "[0] Heading 1 Avtal"
    for messages in raise_payloads + moderate_payloads:
        systems = [
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "system"
        ]
        assert any(intent in text and heading_line in text for text in systems)
        assert "Granskningsavsikt" in "\n".join(systems)
    assert heading_payloads
    heading_systems = [
        str(message.get("content") or "")
        for messages in heading_payloads
        for message in messages
        if message.get("role") == "system"
    ]
    assert any(intent in text for text in heading_systems)


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
            return WordExpertComment(
                kommentar="Tidsfrist och påföljd behöver samordnas.",
                anchor_paragraph_index=2,
            )
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
async def test_word_review_commits_after_section_not_during_analysis(
    client: AsyncClient,
):
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
    assert seen_during_heading == [0]


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
    actions = (await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")).json()
    comments = [row for row in actions if row["action_type"] == "comment"]
    replacements = [row for row in actions if row["action_type"] == "replace"]
    assert comments and replacements
    assert max(row["source"]["ordinal"] for row in comments) < min(
        row["source"]["ordinal"] for row in replacements
    )


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
                kommentar="Tidsallokeringen är otydlig och bör preciseras.",
                anchor_paragraph_index=2,
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
                    _issue(
                        observation_ids=observation_ids,
                        paragraph_index=max(
                            issue.paragraph_index for issue in parsed.issues
                        ),
                        supporting_expert_ids=expert_ids,
                        short_comment=(
                            "Byt 'försöker i möjligaste mån' mot ett konkret åtagande."
                        ),
                        explanation=(
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
    assert comments[0]["kommentar"] == (
        "Byt 'försöker i möjligaste mån' mot ett konkret åtagande."
    )
    actions = (await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")).json()
    comment_actions = [row for row in actions if row["action_type"] == "comment"]
    assert len(comment_actions) == 1
    assert comment_actions[0]["content"].endswith(
        "Byt 'försöker i möjligaste mån' mot ett konkret åtagande."
    )
    assert "slapphetsutrymme" not in comment_actions[0]["content"]
    assert "för svagt" in comment_actions[0]["explanation"]


@pytest.mark.asyncio
async def test_word_review_does_not_materialize_low_value_or_overlap(
    client: AsyncClient,
):
    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if response_model is WordBatchModeration:
            return _moderation_for_batch(user)
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Ett komma saknas i ingressen.")
        if response_model is WordCommentConvergence:
            parsed = _passthrough_comment_convergence(user)
            ids = [
                observation_id
                for issue in parsed.issues
                for observation_id in issue.observation_ids
            ]
            first, *rest = ids or ["o1"]
            issues = [
                _issue(
                    observation_ids=[first],
                    paragraph_index=1,
                    short_comment="Ett komma saknas i ingressen.",
                    explanation="Rent kosmetiskt.",
                    materiality="low",
                    actionability="informational",
                    should_materialize=True,
                )
            ]
            if rest:
                issues.append(
                    _issue(
                        observation_ids=rest,
                        paragraph_index=1,
                        short_comment="Samma kommatering igen.",
                        explanation="Redan täckt.",
                        novelty="overlap",
                        should_materialize=True,
                    )
                )
            return WordCommentConvergence(issues=issues)
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
            paragraphs=[_para(1, "Konsulten försöker i möjligaste mån leverera i tid.")],
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
    actions = (await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")).json()
    assert comments == []
    assert [row["action_type"] for row in actions] == []


@pytest.mark.asyncio
async def test_word_review_intent_changes_materialization_context(
    client: AsyncClient,
):
    captured: list[str] = []

    async def completer(messages, response_model):
        if response_model is WordCommentConvergence:
            captured.append("\n".join(item["content"] for item in messages))
        user = messages[-1]["content"]
        if response_model is WordBatchModeration:
            return _moderation_for_batch(user)
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Ingressen har ett extra mellanslag.")
        if response_model is WordCommentConvergence:
            parsed = _passthrough_comment_convergence(user)
            return WordCommentConvergence(
                issues=[
                    _issue(
                        observation_ids=[
                            oid
                            for issue in parsed.issues
                            for oid in issue.observation_ids
                        ],
                        paragraph_index=1,
                        short_comment="Ta bort det extra mellanslaget.",
                        explanation="Kosmetiskt och utanför betalningsfokuset.",
                        materiality="low",
                        actionability="informational",
                        should_materialize=False,
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
            paragraphs=[_para(1, "Fakturan ska betalas inom trettio dagar.")],
            review_intent="Granska bara betalningsvillkor.",
            intent_interview={
                "document_type": "contract",
                "questions": [
                    {
                        "id": "focus",
                        "text": "Vad ska granskningen prioritera?",
                        "type": "single_choice",
                        "required": True,
                        "rationale": "Styr vad som är materiellt.",
                        "options": [
                            {"value": "payment", "label": "Betalning"},
                            {"value": "style", "label": "Språk"},
                        ],
                    }
                ],
            },
            intent_answers=[{"question_id": "focus", "selected_values": ["payment"]}],
        ),
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    stored = (await client.get(f"/jobs/{job_id}")).json()["request"]
    assert stored["review_intent"] == "Granska bara betalningsvillkor."
    assert "Betalning" not in stored["review_intent"]
    await jobs_service._run_job(job_id)
    assert captured
    assert "Granska bara betalningsvillkor" in captured[0]
    assert "Betalning" in captured[0]
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    comments = [
        row
        for row in rows
        if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]
    ]
    actions = (await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")).json()
    assert comments == []
    assert actions == []


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
                    _issue(
                        observation_ids=[
                            oid for issue in parsed.issues for oid in issue.observation_ids
                        ],
                        paragraph_index=1,
                        supporting_expert_ids=[
                            expert_id
                            for issue in parsed.issues
                            for expert_id in issue.supporting_expert_ids
                        ],
                        short_comment="Dröjsmålsräntan är acceptabel.",
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
async def test_word_review_retries_truncated_comment_json(client: AsyncClient):
    comment_calls = 0

    async def completer(messages, response_model):
        nonlocal comment_calls
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            comment_calls += 1
            if comment_calls == 1:
                raise _truncated_expert_json_error()
            return WordExpertComment(
                kommentar="Immaterialrättsklausulen är för vid.",
                anchor_paragraph_index=1,
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
                _para(1, "Leverantören behåller all immaterialrätt till underlaget.")
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
    assert comment_calls == 2
    assert [row["kommentar"] for row in comments] == [
        "Immaterialrättsklausulen är för vid."
    ]
    assert comments[0]["paragraph_index"] == 1


@pytest.mark.asyncio
async def test_word_review_second_truncated_comment_fails_job(client: AsyncClient):
    async def completer(messages, response_model):
        if response_model is WordBatchModeration:
            return _moderation_for_batch(messages[-1]["content"])
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            raise _truncated_expert_json_error()
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client, n=1)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[
                _para(1, "Leverantören behåller all immaterialrätt till underlaget.")
            ],
        ),
    )
    job_id = created.json()["job_id"]
    await jobs_service._run_job(job_id)
    job = (await client.get(f"/jobs/{job_id}")).json()
    assert job["status"] == "failed"
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    comments = [
        row
        for row in rows
        if not row["is_heading_suggestion"] and not row["is_rewrite_suggestion"]
    ]
    assert comments == []
    assert all("Immaterialrätt" not in (row.get("kommentar") or "") for row in rows)


@pytest.mark.asyncio
async def test_word_review_never_persists_anchor_outside_question_indexes(
    client: AsyncClient,
):
    async def completer(messages, response_model):
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="Flera stycken.",
                questions=[
                    WordReviewQuestion(
                        id="q1",
                        paragraph_indexes=[1, 2, 3],
                        question="Vad bör kommenteras?",
                        why_it_matters="Fel ankare får inte sparas.",
                    )
                ],
            )
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            return WordExpertComment(
                kommentar="Felankrad kommentar",
                anchor_paragraph_index=99,
            )
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client, n=1)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[
                _para(1, "Leverantören behåller all immaterialrätt till underlaget."),
                _para(2, "Beställaren ska betala fakturan inom trettio dagar."),
                _para(3, "Avtalet gäller i tolv månader från undertecknandet."),
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
    assert comments == []
    assert all(row["paragraph_index"] != 99 for row in rows)


@pytest.mark.asyncio
async def test_word_review_uses_explicit_anchor_and_drops_invalid(
    client: AsyncClient,
):
    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="IP och betalning.",
                questions=[
                    WordReviewQuestion(
                        id="q1",
                        paragraph_indexes=[1, 2, 3],
                        question="Var sitter immaterialrätten?",
                        why_it_matters="Fel ankare flyttar kommentaren.",
                    )
                ],
            )
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            if "behåller all immaterialrätt" in user:
                return WordExpertComment(
                    kommentar="IP-klausulen är för vid.",
                    anchor_paragraph_index=1,
                )
            return WordExpertComment(kommentar="x", anchor_paragraph_index=99)
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
                _para(1, "Leverantören behåller all immaterialrätt till underlaget."),
                _para(2, "Beställaren ska betala fakturan inom trettio dagar."),
                _para(3, "Avtalet gäller i tolv månader från undertecknandet."),
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
    assert [row["paragraph_index"] for row in comments] == [1]
    assert comments[0]["kommentar"] == "IP-klausulen är för vid."


@pytest.mark.asyncio
async def test_word_review_drops_multi_paragraph_comment_without_anchor(
    client: AsyncClient,
):
    async def completer(messages, response_model):
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="Flera stycken.",
                questions=[
                    WordReviewQuestion(
                        id="q1",
                        paragraph_indexes=[1, 2],
                        question="Hör tidsfrist och påföljd ihop?",
                        why_it_matters="Ankare krävs.",
                    )
                ],
            )
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(question_ids=["q1"])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Ska inte gissas till fel stycke.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client, n=1)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[
                _para(1, "Beställaren ska betala fakturan inom trettio dagar."),
                _para(2, "Avtalet gäller i tolv månader från undertecknandet."),
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
    assert comments == []


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
    listed = (await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")).json()
    assert listed[0]["anchor"]["paragraph_index"] == 1
    assert listed[0]["anchor"]["reviewed_text"]
    assert listed[0]["anchor"]["text_hash"]
    row_id = listed[0]["id"]
    claimed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{row_id}/claim",
        json={"application_id": "app-patch"},
    )
    assert claimed.status_code == 200
    completed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{row_id}/complete",
        json={"application_id": "app-patch", "word_artifact_id": "w-1"},
    )
    assert completed.status_code == 200
    assert completed.json()["word_artifact_id"] == "w-1"
    assert completed.json()["status"] == "applied"


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
                "task": _review_task(panel_id),
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


@pytest.mark.asyncio
async def test_latest_word_job_includes_failed_job_error(client: AsyncClient):
    panel_id = await _create_expert_panel(client)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            doc_id="failed-resume-doc",
            paragraphs=[_para(1, "Detta stycke är tillräckligt långt.")],
        ),
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        job.status = "failed"
        job.error = "WordCommentConvergence/json_invalid"
        await session.commit()
    latest = await client.get(
        "/expertgranskning/word-jobs/latest",
        params={"doc_id": "failed-resume-doc"},
    )
    assert latest.status_code == 200
    body = latest.json()
    assert body["job_id"] == job_id
    assert body["status"] == "failed"
    assert body["error"] == "WordCommentConvergence/json_invalid"


@pytest.mark.asyncio
async def test_word_review_publishes_first_section_before_later_sections(
    client: AsyncClient, monkeypatch
):
    events: list[dict] = []
    release_slow = asyncio.Event()
    saw_slow = asyncio.Event()
    original = expertgranskning_broadcast.publish

    async def capture(job_id: str, event: dict) -> None:
        events.append(event)
        await original(job_id, event)

    monkeypatch.setattr(expertgranskning_broadcast, "publish", capture)

    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if "Långsam sektion" in user and response_model is WordBatchModeration:
            saw_slow.set()
            await release_slow.wait()
        if response_model is WordBatchModeration:
            return _moderation_for_batch(user)
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(
                question_ids=_question_ids_from_user(user)[:1]
            )
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Sektionskommentar.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text="", motivering="")
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(user)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client, n=1)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json={
            "task": _review_task(panel_id),
            "doc_id": "doc-progressive",
            "sections": [
                {
                    "heading": "Snabb sektion",
                    "heading_style": "Heading 1",
                    "heading_paragraph_index": 0,
                    "paragraphs": [
                        _para(
                            1,
                            "Detta stycke är tillräckligt långt för granskning.",
                        ).model_dump()
                    ],
                },
                {
                    "heading": "Långsam sektion",
                    "heading_style": "Heading 1",
                    "heading_paragraph_index": 2,
                    "paragraphs": [
                        _para(
                            3,
                            "Detta andra stycke är också tillräckligt långt.",
                        ).model_dump()
                    ],
                },
            ],
        },
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    runner = asyncio.create_task(jobs_service._run_job(job_id))
    await saw_slow.wait()
    for _ in range(50):
        if any(
            event.get("type") == "expertgranskning.progress"
            and event.get("sections_completed") == 1
            for event in events
        ):
            break
        await asyncio.sleep(0.02)
    progress = [
        event
        for event in events
        if event.get("type") == "expertgranskning.progress"
    ]
    created_actions = [
        event
        for event in events
        if event.get("type") == "expertgranskning.action.created"
    ]
    assert progress and progress[0]["sections_completed"] == 1
    assert progress[0]["sections_total"] == 2
    assert progress[0]["actions_created"] >= 1
    assert created_actions
    assert all(event.get("type") != "expertgranskning.finished" for event in events)
    release_slow.set()
    await runner
    types = [event["type"] for event in events]
    assert types.count("expertgranskning.progress") == 2
    assert types[-1] == "expertgranskning.finished"
    assert events[-1]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_word_review_keeps_first_section_when_later_section_fails(
    client: AsyncClient, monkeypatch
):
    events: list[dict] = []
    release_fail = asyncio.Event()
    original = expertgranskning_broadcast.publish

    async def capture(job_id: str, event: dict) -> None:
        events.append(event)
        await original(job_id, event)

    monkeypatch.setattr(expertgranskning_broadcast, "publish", capture)

    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if "Långsam sektion" in user and response_model is WordBatchModeration:
            await release_fail.wait()
            raise RuntimeError("section two boom")
        if response_model is WordBatchModeration:
            return _moderation_for_batch(user)
        if response_model is WordExpertRaiseHand:
            return WordExpertRaiseHand(
                question_ids=_question_ids_from_user(user)[:1]
            )
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Behållen kommentar.")
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag=None)
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text="", motivering="")
        if response_model is WordCommentConvergence:
            return _passthrough_comment_convergence(user)
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client, n=1)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json={
            "task": _review_task(panel_id),
            "doc_id": "doc-partial-fail",
            "sections": [
                {
                    "heading": "Snabb sektion",
                    "heading_style": "Heading 1",
                    "heading_paragraph_index": 0,
                    "paragraphs": [
                        _para(
                            1,
                            "Detta stycke är tillräckligt långt för granskning.",
                        ).model_dump()
                    ],
                },
                {
                    "heading": "Långsam sektion",
                    "heading_style": "Heading 1",
                    "heading_paragraph_index": 2,
                    "paragraphs": [
                        _para(
                            3,
                            "Detta andra stycke är också tillräckligt långt.",
                        ).model_dump()
                    ],
                },
            ],
        },
    )
    job_id = created.json()["job_id"]
    runner = asyncio.create_task(jobs_service._run_job(job_id))
    for _ in range(50):
        if any(
            event.get("type") == "expertgranskning.progress"
            and event.get("sections_completed") == 1
            for event in events
        ):
            break
        await asyncio.sleep(0.02)
    assert any(
        event.get("type") == "expertgranskning.action.created" for event in events
    )
    release_fail.set()
    await runner
    types = [event["type"] for event in events]
    assert "expertgranskning.action.created" in types
    assert types[-1] == "expertgranskning.finished"
    assert events[-1]["status"] == "failed"
    assert "section two boom" in (events[-1].get("error") or "")
    rows = (await client.get(f"/expertgranskning/word-jobs/{job_id}/results")).json()
    assert {row["paragraph_index"] for row in rows} == {1}
