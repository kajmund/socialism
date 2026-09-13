"""Actor-context contract: perspective control, not advocacy filtering."""

from __future__ import annotations

import pytest

from app.llm import set_structured_completer
from app.services import jobs as jobs_service
from app.services.expertgranskning.actor_context import (
    ACTOR_CONTEXT_HEADING,
    ACTOR_CONTEXT_KNOWN_KEY,
    ACTOR_CONTEXT_UNKNOWN_KEY,
    ActorContext,
    actor_context_source_text,
    finalize_actor_context,
    has_usable_actor_source,
    render_actor_context,
    resolve_actor_context,
    unknown_actor_context,
)
from app.services.expertgranskning.schemas import (
    DocumentIntentInterview,
    IntentAnswer,
    WordBatchModeration,
    WordCommentConvergence,
    WordDocumentSection,
    WordExpertComment,
    WordExpertRaiseHand,
    WordExpertRoute,
    WordHeadingAssessment,
    WordReviewQuestion,
    WordRewriteSuggestion,
)
from app.services.expertgranskning.word_review import (
    _analyze_batch,
    _comment_convergence,
    _comment_question,
    _messages_with_brief,
    _review_heading,
    _rewrite_convergence,
    log_word_review_call_summary,
)
from app.services.expertgranskning.word_review_timing import (
    WordReviewLimiter,
    WordReviewTimings,
)
from app.services.panel.schemas import PanelExpertSlot
from app.services.prompt_catalog import default_prompts
from tests.test_expertgranskning_word_review import (
    _create_expert_panel,
    _obs,
    _para,
    _payload,
    _review_question,
    _review_section,
    _review_slots,
)
from tests.test_intent_interview import _choice_question, _interview


def _en_prompts() -> dict[str, str]:
    return default_prompts("en")


def _render(context: ActorContext, prompts: dict[str, str] | None = None) -> str:
    return render_actor_context(context, prompts or _en_prompts())


CHALLENGER_DOCUMENT = (
    "The challenging members request that the association decision "
    "should be attacked as invalid."
)
ASSOCIATION_INTENT = "We represent the association, not the challenging members"
CHALLENGER_INTENT = "We represent the challengers"


def _party_interview() -> DocumentIntentInterview:
    return DocumentIntentInterview.model_validate(_interview(_choice_question()))


def _custom_answer(text: str) -> list[IntentAnswer]:
    return [
        IntentAnswer.model_validate(
            {
                "question_id": "party",
                "selected_values": [],
                "free_text": text,
            }
        )
    ]


def _association_context() -> ActorContext:
    return ActorContext(
        user_role="counsel for the association",
        counterpart_or_audience="challenging members",
        relationship="represents the association against a challenge",
        review_goal="identify legal risk and defense options for the association",
        output_perspective="advice for the association",
        perspective_known=True,
    )


def _challenger_context() -> ActorContext:
    return ActorContext(
        user_role="counsel for the challengers",
        counterpart_or_audience="the association",
        relationship="represents members challenging a decision",
        review_goal="identify grounds to challenge the association decision",
        output_perspective="advice for the challengers",
        perspective_known=True,
    )


def _cv_interview() -> DocumentIntentInterview:
    return DocumentIntentInterview.model_validate(
        {
            "document_type": "cv",
            "questions": [
                {
                    "id": "role",
                    "text": "Are you the candidate or the evaluator?",
                    "type": "single_choice",
                    "required": True,
                    "rationale": "Changes whether advice improves the CV or assesses the candidate.",
                    "options": [
                        {"value": "candidate", "label": "Candidate"},
                        {"value": "recruiter", "label": "Recruiter"},
                    ],
                }
            ],
        }
    )


def _choice_answers(question_id: str, value: str) -> list[IntentAnswer]:
    return [
        IntentAnswer.model_validate(
            {"question_id": question_id, "selected_values": [value]}
        )
    ]


def _system_texts(messages: list[dict[str, str]]) -> list[str]:
    return [
        str(message.get("content") or "")
        for message in messages
        if message.get("role") == "system"
    ]


def test_source_uses_intent_not_document_voice():
    source = actor_context_source_text(
        interview=_party_interview(),
        answers=_custom_answer(ASSOCIATION_INTENT),
        review_intent="Defend the association's decision.",
    )
    assert ASSOCIATION_INTENT in source
    assert "Inferred document type: contract" in source
    assert "Defend the association's decision." in source
    assert "should be attacked as invalid" not in source
    assert CHALLENGER_DOCUMENT not in source


def test_source_opposite_intent_is_not_association():
    association = actor_context_source_text(
        interview=_party_interview(),
        answers=_custom_answer(ASSOCIATION_INTENT),
        review_intent="",
    )
    challenger = actor_context_source_text(
        interview=_party_interview(),
        answers=_custom_answer(CHALLENGER_INTENT),
        review_intent="",
    )
    assert ASSOCIATION_INTENT in association
    assert CHALLENGER_INTENT in challenger
    assert ASSOCIATION_INTENT not in challenger
    assert CHALLENGER_INTENT not in association


def test_no_usable_source_when_intent_and_answers_absent():
    interview = DocumentIntentInterview.model_validate(
        {"document_type": "memo", "questions": []}
    )
    assert has_usable_actor_source(interview, [], "") is False
    assert has_usable_actor_source(None, [], "") is False
    assert has_usable_actor_source(None, [], "  ") is False
    assert has_usable_actor_source(None, [], "Focus on tone.") is True


def test_known_render_orients_advice_to_user_role():
    text = _render(_association_context())
    assert text.startswith(ACTOR_CONTEXT_HEADING)
    assert "Perspective is known. This is perspective control, not advocacy." in text
    assert "User role: counsel for the association" in text
    assert "Counterpart or audience: challenging members" in text
    assert "Output perspective: advice for the association" in text
    assert "Address recommendations and actions to the user's role" in text
    assert "Do not turn it into advice to the user" in text
    assert "Do not advise attacking, challenging" in text
    assert CHALLENGER_DOCUMENT not in text


def test_opposite_render_orients_to_challengers():
    left = _render(_association_context())
    right = _render(_challenger_context())
    assert "counsel for the association" in left
    assert "counsel for the challengers" in right
    assert "counsel for the association" not in right
    assert "counsel for the challengers" not in left
    assert "advice for the challengers" in right
    assert "Perspective is known. This is perspective control, not advocacy." in left
    assert "Perspective is known. This is perspective control, not advocacy." in right


def test_cv_candidate_and_recruiter_renders_differ():
    candidate = _render(
        ActorContext(
            user_role="candidate submitting the CV",
            counterpart_or_audience="recruiter",
            relationship="author of the CV",
            review_goal="improve how the candidate presents themselves",
            output_perspective="advice for the candidate",
            perspective_known=True,
        )
    )
    recruiter = _render(
        ActorContext(
            user_role="recruiter evaluating the candidate",
            counterpart_or_audience="candidate",
            relationship="receiving-side reader",
            review_goal="assess the candidate for hiring",
            output_perspective="assessment for the receiving side",
            perspective_known=True,
        )
    )
    assert "candidate submitting the CV" in candidate
    assert "improve how the candidate presents themselves" in candidate
    assert "recruiter evaluating the candidate" in recruiter
    assert "assess the candidate for hiring" in recruiter
    assert "candidate submitting the CV" not in recruiter
    assert "recruiter evaluating the candidate" not in candidate


def test_unknown_render_is_neutral_and_invents_no_role():
    text = _render(unknown_actor_context())
    assert text == _en_prompts()[ACTOR_CONTEXT_UNKNOWN_KEY]
    assert "Perspective is unknown" in text
    assert "User role:" not in text
    assert "Do not invent a side" in text
    assert "association" not in text.lower()
    assert "challenger" not in text.lower()
    assert "candidate" not in text.lower()


def test_render_uses_active_prompt_map_for_known_perspective():
    prompts = _en_prompts()
    prompts[ACTOR_CONTEXT_KNOWN_KEY] = (
        "OVERRIDE-KNOWN role={user_role} goal={review_goal} "
        "out={output_perspective}"
    )
    text = render_actor_context(_association_context(), prompts)
    assert text == (
        "OVERRIDE-KNOWN role=counsel for the association "
        "goal=identify legal risk and defense options for the association "
        "out=advice for the association"
    )
    assert "Perspective is known" not in text


def test_render_uses_active_prompt_map_for_unknown_perspective():
    prompts = _en_prompts()
    prompts[ACTOR_CONTEXT_UNKNOWN_KEY] = "OVERRIDE-UNKNOWN-NEUTRAL"
    text = render_actor_context(unknown_actor_context(), prompts)
    assert text == "OVERRIDE-UNKNOWN-NEUTRAL"
    assert "Perspective is unknown" not in text


def test_render_fails_loud_when_unknown_prompt_missing():
    prompts = _en_prompts()
    del prompts[ACTOR_CONTEXT_UNKNOWN_KEY]
    with pytest.raises(RuntimeError, match="actor_context.unknown"):
        render_actor_context(unknown_actor_context(), prompts)


def test_render_fails_loud_when_known_prompt_missing():
    prompts = _en_prompts()
    del prompts[ACTOR_CONTEXT_KNOWN_KEY]
    with pytest.raises(RuntimeError, match="actor_context.known"):
        render_actor_context(_association_context(), prompts)


def test_render_uses_swedish_catalog_wording():
    prompts = default_prompts("sv")
    known = render_actor_context(_association_context(), prompts)
    assert known.startswith("Aktörskontext")
    assert "Perspektivet är känt" in known
    assert "Användarroll: counsel for the association" in known
    assert "Perspective is known" not in known
    unknown = render_actor_context(unknown_actor_context(), prompts)
    assert unknown == prompts[ACTOR_CONTEXT_UNKNOWN_KEY]
    assert "Perspektivet är okänt" in unknown
    assert "Perspective is unknown" not in unknown


def test_finalize_unknown_when_role_missing():
    raw = ActorContext(
        user_role="",
        counterpart_or_audience="someone",
        perspective_known=True,
    )
    assert finalize_actor_context(raw) == unknown_actor_context()


@pytest.mark.asyncio
async def test_resolver_skips_llm_when_source_absent():
    calls: list[str] = []

    async def completer(messages, response_model):
        calls.append(response_model.__name__)
        raise AssertionError(response_model)

    set_structured_completer(completer)
    timings = WordReviewTimings()
    resolved = await resolve_actor_context(
        prompts=default_prompts("sv"),
        interview=None,
        answers=[],
        review_intent="",
        limiter=WordReviewLimiter(1, timings),
    )
    assert resolved == unknown_actor_context()
    assert calls == []
    snapshot = timings.snapshot()
    assert snapshot["actor_context_resolved"] == 0
    assert snapshot["actor_context_resolver_calls"] == 0
    assert snapshot["llm_call_count"] == 0


@pytest.mark.asyncio
async def test_resolver_uses_interview_not_document_and_records_telemetry():
    seen: list[str] = []

    async def completer(messages, response_model):
        assert response_model is ActorContext
        seen.extend(str(message.get("content") or "") for message in messages)
        return _association_context()

    set_structured_completer(completer)
    timings = WordReviewTimings()
    resolved = await resolve_actor_context(
        prompts=default_prompts("sv"),
        interview=_party_interview(),
        answers=_custom_answer(ASSOCIATION_INTENT),
        review_intent="",
        limiter=WordReviewLimiter(1, timings),
    )
    joined = "\n".join(seen)
    assert ASSOCIATION_INTENT in joined
    assert "should be attacked as invalid" not in joined
    assert CHALLENGER_DOCUMENT not in joined
    assert resolved.perspective_known is True
    assert resolved.user_role == "counsel for the association"
    snapshot = timings.snapshot()
    assert snapshot["actor_context_resolved"] == 1
    assert snapshot["actor_context_resolver_calls"] == 1
    dumped = repr(snapshot)
    assert ASSOCIATION_INTENT not in dumped
    assert "counsel for the association" not in dumped


@pytest.mark.asyncio
async def test_resolver_opposite_intent_can_return_opposite_context():
    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if ASSOCIATION_INTENT in user:
            return _association_context()
        if CHALLENGER_INTENT in user:
            return _challenger_context()
        raise AssertionError(user)

    set_structured_completer(completer)
    prompts = default_prompts("sv")
    left = await resolve_actor_context(
        prompts=prompts,
        interview=_party_interview(),
        answers=_custom_answer(ASSOCIATION_INTENT),
        review_intent="",
        limiter=WordReviewLimiter(1, WordReviewTimings()),
    )
    right = await resolve_actor_context(
        prompts=prompts,
        interview=_party_interview(),
        answers=_custom_answer(CHALLENGER_INTENT),
        review_intent="",
        limiter=WordReviewLimiter(1, WordReviewTimings()),
    )
    assert left.user_role == "counsel for the association"
    assert right.user_role == "counsel for the challengers"
    assert left.output_perspective != right.output_perspective


@pytest.mark.asyncio
async def test_resolver_cv_candidate_versus_recruiter():
    async def completer(messages, response_model):
        user = messages[-1]["content"]
        if "Candidate" in user:
            return ActorContext(
                user_role="candidate",
                counterpart_or_audience="recruiter",
                relationship="submitting the CV",
                review_goal="improve presentation",
                output_perspective="advice for the candidate",
                perspective_known=True,
            )
        if "Recruiter" in user:
            return ActorContext(
                user_role="recruiter",
                counterpart_or_audience="candidate",
                relationship="evaluating the CV",
                review_goal="assess the candidate",
                output_perspective="assessment for the receiving side",
                perspective_known=True,
            )
        raise AssertionError(user)

    set_structured_completer(completer)
    prompts = default_prompts("sv")
    interview = _cv_interview()
    candidate = await resolve_actor_context(
        prompts=prompts,
        interview=interview,
        answers=_choice_answers("role", "candidate"),
        review_intent="",
        limiter=WordReviewLimiter(1, WordReviewTimings()),
    )
    recruiter = await resolve_actor_context(
        prompts=prompts,
        interview=interview,
        answers=_choice_answers("role", "recruiter"),
        review_intent="",
        limiter=WordReviewLimiter(1, WordReviewTimings()),
    )
    assert candidate.user_role == "candidate"
    assert recruiter.user_role == "recruiter"
    assert "candidate" in candidate.output_perspective
    assert "receiving side" in recruiter.output_perspective


def test_actor_context_system_message_precedes_document_brief():
    actor = _render(_association_context())
    brief = f"[1] {CHALLENGER_DOCUMENT}"
    messages = _messages_with_brief(
        identity="expert",
        actor_context=actor,
        brief=brief,
        user="Comment on the paragraph.",
    )
    systems = _system_texts(messages)
    assert systems[0] == "expert"
    assert systems[1] == actor
    assert systems[2] == brief
    assert systems.index(actor) < systems.index(brief)
    assert "should be attacked as invalid" not in actor
    assert "counsel for the association" in actor


@pytest.mark.asyncio
async def test_comment_question_keeps_association_perspective_above_document_voice():
    captured: list[list[dict[str, str]]] = []

    async def completer(messages, response_model):
        captured.append(messages)
        return WordExpertComment(
            kommentar="This is a serious weakness for the association.",
            anchor_paragraph_index=1,
        )

    set_structured_completer(completer)
    actor = _render(_association_context())
    brief = f"[1] {CHALLENGER_DOCUMENT}"
    rows = await _comment_question(
        prompts=default_prompts("sv"),
        slot=PanelExpertSlot(slot_id="jurist", label="Jurist", profile="Avtal"),
        brief=brief,
        section=_review_section([_para(1, CHALLENGER_DOCUMENT)]),
        question=WordReviewQuestion(
            id="q1",
            paragraph_indexes=[1],
            question="What is the risk in this decision?",
            why_it_matters="Validity.",
        ),
        paragraphs=[_para(1, CHALLENGER_DOCUMENT)],
        limiter=WordReviewLimiter(1, WordReviewTimings()),
        actor_context=actor,
    )
    assert captured
    systems = _system_texts(captured[0])
    assert any(ACTOR_CONTEXT_HEADING in item for item in systems)
    actor_msg = next(item for item in systems if ACTOR_CONTEXT_HEADING in item)
    brief_msg = next(item for item in systems if CHALLENGER_DOCUMENT in item)
    assert systems.index(actor_msg) < systems.index(brief_msg)
    assert "counsel for the association" in actor_msg
    assert "Do not advise attacking, challenging" in actor_msg
    assert "should be attacked as invalid" not in actor_msg
    user = captured[0][-1]["content"]
    assert "aktörskontexten" in user or "actor context" in user.lower()
    slot, _question, draft, anchor = rows[0]
    assert draft.kommentar == "This is a serious weakness for the association."
    assert anchor == 1
    assert slot.slot_id == "jurist"


@pytest.mark.asyncio
async def test_comment_question_opposite_intent_uses_challenger_actor_context():
    captured: list[str] = []

    async def completer(messages, response_model):
        captured.extend(_system_texts(messages))
        return WordExpertComment(kommentar="Challenge the decision.", anchor_paragraph_index=1)

    set_structured_completer(completer)
    actor = _render(_challenger_context())
    await _comment_question(
        prompts=default_prompts("sv"),
        slot=PanelExpertSlot(slot_id="jurist", label="Jurist", profile="Avtal"),
        brief=f"[1] {CHALLENGER_DOCUMENT}",
        section=_review_section([_para(1, CHALLENGER_DOCUMENT)]),
        question=WordReviewQuestion(
            id="q1",
            paragraph_indexes=[1],
            question="What is the risk in this decision?",
            why_it_matters="Validity.",
        ),
        paragraphs=[_para(1, CHALLENGER_DOCUMENT)],
        limiter=WordReviewLimiter(1, WordReviewTimings()),
        actor_context=actor,
    )
    joined = "\n".join(captured)
    assert "counsel for the challengers" in joined
    assert "counsel for the association" not in joined
    assert "advice for the challengers" in joined


@pytest.mark.asyncio
async def test_unknown_actor_context_stays_neutral_on_comment_call():
    captured: list[str] = []

    async def completer(messages, response_model):
        captured.extend(_system_texts(messages))
        return WordExpertComment(kommentar="The wording is unclear.", anchor_paragraph_index=1)

    set_structured_completer(completer)
    actor = _render(unknown_actor_context())
    await _comment_question(
        prompts=default_prompts("sv"),
        slot=PanelExpertSlot(slot_id="jurist", label="Jurist", profile="Avtal"),
        brief="[1] Ordinary memo text that is long enough.",
        section=_review_section([_para(1, "Ordinary memo text that is long enough.")]),
        question=WordReviewQuestion(
            id="q1",
            paragraph_indexes=[1],
            question="Is the wording clear?",
            why_it_matters="Clarity.",
        ),
        paragraphs=[_para(1, "Ordinary memo text that is long enough.")],
        limiter=WordReviewLimiter(1, WordReviewTimings()),
        actor_context=actor,
    )
    joined = "\n".join(captured)
    assert "Perspective is unknown" in joined
    assert "Do not invent a side" in joined
    assert "User role:" not in joined
    assert "association" not in joined.lower()
    assert "challenger" not in joined.lower()


@pytest.mark.asyncio
async def test_analyze_batch_passes_actor_context_to_moderator_router_and_experts():
    seen: list[tuple[str, list[str]]] = []

    async def completer(messages, response_model):
        seen.append((response_model.__name__, _system_texts(messages)))
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="Needs review.",
                questions=[_review_question("q1", [1], primary=1)],
            )
        if response_model is WordExpertRoute:
            return WordExpertRoute(expert_ids=["jurist"])
        if response_model is WordExpertComment:
            return WordExpertComment(kommentar="Association risk.", anchor_paragraph_index=1)
        raise AssertionError(response_model)

    set_structured_completer(completer)
    actor = _render(_association_context())
    await _analyze_batch(
        batch_index=0,
        batch=[_para(1, "Ett giltigt stycke att granska här.")],
        section=_review_section([_para(1, "Ett giltigt stycke att granska här.")]),
        prompts=default_prompts("sv"),
        slots=_review_slots(),
        brief=f"[1] {CHALLENGER_DOCUMENT}",
        review_intent="",
        review_context="Structured review context",
        router_context="Structured review context",
        target=None,
        limiter=WordReviewLimiter(4, WordReviewTimings()),
        actor_context=actor,
    )
    names = [name for name, _systems in seen]
    assert names == ["WordBatchModeration", "WordExpertRoute", "WordExpertComment"]
    for name, systems in seen:
        joined = "\n".join(systems)
        assert ACTOR_CONTEXT_HEADING in joined, name
        assert "counsel for the association" in joined, name
        actor_indexes = [
            index
            for index, text in enumerate(systems)
            if text.startswith(ACTOR_CONTEXT_HEADING)
        ]
        assert actor_indexes, name
        brief_indexes = [
            index for index, text in enumerate(systems) if CHALLENGER_DOCUMENT in text
        ]
        if brief_indexes:
            assert actor_indexes[0] < brief_indexes[0], name


@pytest.mark.asyncio
async def test_analyze_batch_raise_hand_receives_actor_context():
    seen: list[str] = []

    async def completer(messages, response_model):
        if response_model is WordBatchModeration:
            return WordBatchModeration(
                needs_review=True,
                reason="Unsure.",
                questions=[_review_question("q1", [1], primary=1)],
            )
        if response_model is WordExpertRoute:
            return WordExpertRoute(expert_ids=[])
        if response_model is WordExpertRaiseHand:
            seen.extend(_system_texts(messages))
            return WordExpertRaiseHand(question_ids=[])
        raise AssertionError(response_model)

    set_structured_completer(completer)
    actor = _render(_association_context())
    await _analyze_batch(
        batch_index=0,
        batch=[_para(1, "Ett giltigt stycke att granska här.")],
        section=_review_section([_para(1, "Ett giltigt stycke att granska här.")]),
        prompts=default_prompts("sv"),
        slots=_review_slots(),
        brief="Dokumenttext.",
        review_intent="",
        review_context="",
        router_context="",
        target=None,
        limiter=WordReviewLimiter(4, WordReviewTimings()),
        actor_context=actor,
    )
    assert any(ACTOR_CONTEXT_HEADING in text for text in seen)
    assert any("counsel for the association" in text for text in seen)


@pytest.mark.asyncio
async def test_heading_and_rewrite_receive_actor_context():
    seen: dict[str, list[str]] = {}

    async def completer(messages, response_model):
        seen[response_model.__name__] = _system_texts(messages)
        if response_model is WordHeadingAssessment:
            return WordHeadingAssessment(forslag="Clearer heading")
        if response_model is WordRewriteSuggestion:
            return WordRewriteSuggestion(ny_text="Rewritten paragraph.", motivering="Clearer.")
        raise AssertionError(response_model)

    set_structured_completer(completer)
    actor = _render(_association_context())
    prompts = default_prompts("sv")
    limiter = WordReviewLimiter(1, WordReviewTimings())
    section = _review_section([_para(1, "Ett giltigt stycke att granska här.")])
    await _review_heading(
        prompts=prompts,
        slots=_review_slots(),
        section=section,
        limiter=limiter,
        review_intent="Structured review context",
        actor_context=actor,
    )
    await _rewrite_convergence(
        prompts=prompts,
        section=section,
        paragraph=_para(1, "Ett giltigt stycke att granska här."),
        comments=[("Jurist", "This is a weakness for the association.")],
        limiter=limiter,
        review_intent="Structured review context",
        actor_context=actor,
    )
    for name in ("WordHeadingAssessment", "WordRewriteSuggestion"):
        joined = "\n".join(seen[name])
        assert ACTOR_CONTEXT_HEADING in joined
        assert "counsel for the association" in joined


@pytest.mark.asyncio
async def test_convergence_preserves_oriented_observation_and_actor_context():
    captured: list[list[dict[str, str]]] = []
    oriented = (
        "This is a serious weakness for the association; prepare a defense. "
        "Challengers can argue the decision is invalid, but that is their case."
    )

    async def completer(messages, response_model):
        captured.append(messages)
        return WordCommentConvergence(
            issues=[
                {
                    "observation_ids": ["o1"],
                    "paragraph_index": 3,
                    "supporting_expert_ids": ["frank"],
                    "short_comment": oriented,
                    "explanation": oriented,
                    "materiality": "high",
                    "actionability": "actionable",
                    "novelty": "new",
                    "should_materialize": True,
                    "has_dissensus": False,
                }
            ]
        )

    set_structured_completer(completer)
    actor = _render(_association_context())
    observation = _obs(kommentar=oriented)
    section = WordDocumentSection(
        heading="Decision",
        heading_style="Heading 1",
        heading_paragraph_index=0,
        paragraphs=[_para(3, CHALLENGER_DOCUMENT)],
    )
    parsed = await _comment_convergence(
        prompts=default_prompts("sv"),
        section=section,
        batch=list(section.paragraphs),
        observations=[observation],
        limiter=WordReviewLimiter(1, WordReviewTimings()),
        review_intent="Structured review context",
        actor_context=actor,
    )
    systems = _system_texts(captured[0])
    user = captured[0][-1]["content"]
    assert any(ACTOR_CONTEXT_HEADING in item for item in systems)
    assert any("counsel for the association" in item for item in systems)
    assert oriented in user
    assert "Bevara perspektivet" in user or "Preserve the perspective" in user
    assert "Vänd inte" in user or "Do not flip" in user
    assert parsed.issues[0].short_comment == oriented
    assert "you should attack" not in parsed.issues[0].short_comment.lower()
    assert "should be attacked as invalid" not in parsed.issues[0].short_comment


def test_intent_interview_prompt_asks_relationship_without_domain_branch():
    sv = default_prompts("sv")["expertgranskning.word.intent_interview"]
    en = default_prompts("en")["expertgranskning.word.intent_interview"]
    assert "relation till dokumentet" in sv
    assert "kandidaten eller den som bedömer" in sv
    assert "vilken sida användaren företräder" in sv
    assert "relationship to the document" in en
    assert "candidate or the evaluator" in en
    assert "which side the user represents" in en
    assert "if document_type ==" not in sv
    assert "if document_type ==" not in en


def test_expert_and_convergence_prompts_are_perspective_control():
    sv = default_prompts("sv")
    comment = sv["expertgranskning.word.expert.comment"]
    convergence = sv["expertgranskning.word.comment_convergence"]
    rewrite = sv["expertgranskning.word.rewrite_convergence"]
    heading = sv["expertgranskning.word.heading"]
    assert "aktörskontexten" in comment
    assert "perspektivstyrning, inte partsadvocacy" in comment
    assert "Leverantören" not in comment
    assert "Bevara perspektivet" in convergence
    assert "Vänd inte ett korrekt orienterat råd" in convergence
    assert "Vänd inte råden till motparten" in rewrite
    assert "aktörskontexten" in heading


def test_timing_log_has_actor_flags_without_role_text(monkeypatch):
    messages: list[str] = []

    def capture(fmt: str, *args: object) -> None:
        messages.append(fmt % args if args else fmt)

    from app.services.expertgranskning import word_review

    monkeypatch.setattr(word_review.logger, "info", capture)
    timings = WordReviewTimings()
    timings.record_actor_context_resolved(True)
    timings.record_category("actor_context")
    log_word_review_call_summary("job_secret", timings.snapshot(), outcome="success")
    logged = " ".join(messages)
    assert "actor_context_resolved=1" in logged
    assert "actor_context_resolver_calls=1" in logged
    assert "association" not in logged
    assert "challenger" not in logged
    assert "counsel" not in logged


@pytest.mark.asyncio
async def test_resolver_failure_emits_failed_timing_summary(
    client, caplog: pytest.LogCaptureFixture
):
    async def completer(messages, response_model):
        if response_model is ActorContext:
            raise TimeoutError("actor context resolver timed out")
        raise AssertionError(response_model)

    panel_id = await _create_expert_panel(client)
    set_structured_completer(completer)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    created = await client.post(
        "/expertgranskning/word-jobs",
        json=_payload(
            panel_id=panel_id,
            paragraphs=[_para(1, "Ett giltigt stycke att granska här.")],
            review_intent=ASSOCIATION_INTENT,
        ),
    )
    job_id = created.json()["job_id"]
    with caplog.at_level("INFO"):
        await jobs_service._run_job(job_id)
    job = (await client.get(f"/jobs/{job_id}")).json()
    assert job["status"] == "failed"
    assert "timed out" in (job.get("error") or "")
    summaries = [
        record.getMessage()
        for record in caplog.records
        if "Word review LLM calls" in record.getMessage()
    ]
    assert len(summaries) == 1
    message = summaries[0]
    assert f"job_id={job_id}" in message
    assert "outcome=failed" in message
    assert "outcome=success" not in message
    assert "actor_context_resolver_calls=1" in message
    assert "actor_context_resolved=0" in message
    assert ASSOCIATION_INTENT not in message
    timings = [
        record.getMessage()
        for record in caplog.records
        if "Word review timings" in record.getMessage()
    ]
    assert len(timings) == 1
    assert "actor_context_ms=" in timings[0]
    assert "outcome=failed" in timings[0]
