"""Atomic Word comments and perspective-safe claim attribution."""

from __future__ import annotations

from app.services.expertgranskning.actor_context import ActorContext
from app.services.expertgranskning.comment_convergence import (
    WordObservation,
    apply_word_comment_convergence,
    collapse_intra_expert_duplicates,
    consolidated_from_observation,
)
from app.services.expertgranskning.observation import (
    PERSPECTIVE_COUNTERPART,
    PERSPECTIVE_DOCUMENT_AUTHOR,
    PERSPECTIVE_USER,
    WORD_COMMENT_SOFT_CAP_WORDS,
    bind_actor_attribution,
    comment_exceeds_soft_cap,
    comment_misattributes_user_claim,
    comment_word_count,
    draft_from_observation,
    expand_expert_comment,
    materialize_word_comment,
    rewrite_non_user_possessives,
)
from app.services.expertgranskning.schemas import (
    WordCommentConvergence,
    WordConvergedIssue,
    WordExpertComment,
    WordExpertObservation,
)
from app.services.expertgranskning.word_review_timing import WordReviewTimings
from app.services.prompt_catalog import default_prompts


def _actor(*, role: str, counterpart: str, goal: str, perspective: str) -> ActorContext:
    return ActorContext(
        user_role=role,
        counterpart_or_audience=counterpart,
        relationship="represents the named side",
        review_goal=goal,
        output_perspective=perspective,
        perspective_known=True,
    )


def _obs(**overrides) -> WordObservation:
    values = {
        "observation_id": "o1",
        "expert_id": "frank",
        "expert_label": "Frank",
        "question_id": "q1",
        "paragraph_index": 3,
        "paragraph_text": "We request that the decision be annulled.",
        "list_string": "1.",
        "kommentar": "",
        "issue": "The document authors request that the decision be annulled.",
        "analysis": "The request is the document authors' claim, not the user's.",
        "source_perspective": PERSPECTIVE_DOCUMENT_AUTHOR,
        "target_perspective": PERSPECTIVE_USER,
        "statement_owner": PERSPECTIVE_DOCUMENT_AUTHOR,
        "recommendation_recipient": PERSPECTIVE_USER,
        "consequence": "Treating it as the user's request would invert the review.",
        "recommended_action": "From the user's perspective, test whether the request holds.",
    }
    values.update(overrides)
    return WordObservation(**values)


def _issue(**overrides) -> WordConvergedIssue:
    values = {
        "observation_ids": ["o1", "o2"],
        "paragraph_index": 3,
        "supporting_expert_ids": ["frank", "roger"],
        "short_comment": "The document authors request annulment. Test that request.",
        "explanation": "Keep the owner explicit.",
        "materiality": "high",
        "actionability": "actionable",
        "novelty": "new",
        "should_materialize": True,
        "has_dissensus": False,
    }
    values.update(overrides)
    return WordConvergedIssue(**values)


def test_document_author_claim_is_not_called_your_request():
    drifted = "Your request is correctly limited and is your strongest argument."
    assert comment_misattributes_user_claim(drifted, PERSPECTIVE_DOCUMENT_AUTHOR)
    rewritten = rewrite_non_user_possessives(drifted, PERSPECTIVE_DOCUMENT_AUTHOR)
    assert "your request" not in rewritten.casefold()
    assert "your strongest argument" not in rewritten.casefold()
    assert "the document authors" in rewritten.casefold()
    comment = materialize_word_comment(
        issue="Your request is correctly limited.",
        consequence="That wording belongs to the document authors.",
        recommended_action="From the user's perspective, test the request.",
        statement_owner=PERSPECTIVE_DOCUMENT_AUTHOR,
    )
    assert "your request" not in comment.casefold()
    assert "the document authors" in comment.casefold()
    assert "user's perspective" in comment


def test_reversed_actor_context_reverses_recommendation_recipient():
    association = _actor(
        role="counsel for the association",
        counterpart="the challengers",
        goal="defend the decision",
        perspective="advice for the association",
    )
    challenger = _actor(
        role="counsel for the challengers",
        counterpart="the association",
        goal="attack the decision",
        perspective="advice for the challengers",
    )
    raw = WordExpertObservation(
        issue="The decision may be vulnerable on procedure.",
        recommended_action="Prepare the reply.",
        statement_owner=PERSPECTIVE_DOCUMENT_AUTHOR,
        recommendation_recipient=PERSPECTIVE_COUNTERPART,
    )
    for_association = bind_actor_attribution(raw, association)
    for_challenger = bind_actor_attribution(raw, challenger)
    assert for_association.recommendation_recipient == PERSPECTIVE_USER
    assert for_challenger.recommendation_recipient == PERSPECTIVE_USER
    association_comment = materialize_word_comment(
        issue="The challengers request annulment.",
        recommended_action="Prepare the association's reply.",
        statement_owner=PERSPECTIVE_DOCUMENT_AUTHOR,
    )
    challenger_comment = materialize_word_comment(
        issue="The association's decision can be attacked.",
        recommended_action="Prepare the challengers' grounds.",
        statement_owner=PERSPECTIVE_DOCUMENT_AUTHOR,
    )
    assert "association's reply" in association_comment
    assert "challengers' grounds" in challenger_comment
    assert association_comment != challenger_comment


def test_candidate_versus_recruiter_orientation_stays_generic():
    candidate = _actor(
        role="the candidate",
        counterpart="the recruiter",
        goal="strengthen the CV",
        perspective="advice for the candidate",
    )
    recruiter = _actor(
        role="the recruiter",
        counterpart="the candidate",
        goal="evaluate the CV",
        perspective="assessment for the hiring side",
    )
    candidate_obs = bind_actor_attribution(
        WordExpertObservation(
            issue="The CV omits a date range.",
            recommended_action="Add the missing dates.",
            statement_owner=PERSPECTIVE_USER,
        ),
        candidate,
    )
    recruiter_obs = bind_actor_attribution(
        WordExpertObservation(
            issue="The candidate omits a date range.",
            recommended_action="Treat the gap as a screening risk.",
            statement_owner=PERSPECTIVE_DOCUMENT_AUTHOR,
        ),
        recruiter,
    )
    assert candidate_obs.recommendation_recipient == PERSPECTIVE_USER
    assert recruiter_obs.recommendation_recipient == PERSPECTIVE_USER
    candidate_text = materialize_observation_pair(candidate_obs)
    recruiter_text = materialize_observation_pair(recruiter_obs)
    assert "Add the missing dates" in candidate_text
    assert "screening risk" in recruiter_text
    assert candidate_text != recruiter_text


def materialize_observation_pair(item: WordExpertObservation) -> str:
    return materialize_word_comment(
        issue=item.issue,
        recommended_action=item.recommended_action,
        statement_owner=item.statement_owner,
    )


def test_multi_issue_expert_output_stays_atomic():
    parsed = WordExpertComment(
        observations=[
            WordExpertObservation(
                issue="The limitation period is missing.",
                analysis="A long memo about standing, evidence, and costs. " * 20,
                consequence="The claim may be time-barred.",
                recommended_action="Check the limitation date.",
                statement_owner=PERSPECTIVE_DOCUMENT_AUTHOR,
                recommendation_recipient=PERSPECTIVE_USER,
                anchor_paragraph_index=1,
            ),
            WordExpertObservation(
                issue="The requested costs are unspecified.",
                analysis="Another long memo about quantum and interest. " * 20,
                consequence="The amount cannot be tested.",
                recommended_action="Ask for a breakdown.",
                statement_owner=PERSPECTIVE_DOCUMENT_AUTHOR,
                recommendation_recipient=PERSPECTIVE_USER,
                anchor_paragraph_index=2,
            ),
            WordExpertObservation(
                issue="The standing allegation is undeveloped.",
                analysis="A third memo about parties and representation. " * 20,
                consequence="The user cannot meet the allegation as written.",
                recommended_action="Ask who the authors say they represent.",
                statement_owner=PERSPECTIVE_DOCUMENT_AUTHOR,
                recommendation_recipient=PERSPECTIVE_USER,
                anchor_paragraph_index=3,
            ),
        ]
    )
    atoms = expand_expert_comment(parsed)
    assert len(atoms) == 3
    comments = [draft_from_observation(item).kommentar for item in atoms]
    assert all(comment_word_count(text) < 90 for text in comments)
    assert all(not comment_exceeds_soft_cap(text) for text in comments)
    joined = " ".join(comments)
    assert "limitation" in joined
    assert "costs" in joined
    assert "standing" in joined
    assert all("long memo" not in text for text in comments)


def test_single_passthrough_uses_structured_fields_not_raw_analysis():
    observation = _obs(
        analysis=" ".join(["Deep reasoning about both sides and strategy."] * 40),
        kommentar="",
    )
    comment = consolidated_from_observation(observation)
    assert comment_word_count(comment.kommentar) <= WORD_COMMENT_SOFT_CAP_WORDS
    assert "Deep reasoning about both sides" not in comment.kommentar
    assert "Deep reasoning about both sides" in comment.explanation
    assert comment.kommentar != comment.explanation


def test_intra_expert_keeps_separate_issues_from_one_question():
    first = _obs(observation_id="o1", issue="Missing limitation period.")
    second = _obs(
        observation_id="o2",
        issue="Unspecified costs.",
        kommentar="",
        recommended_action="Ask for a breakdown.",
    )
    collapsed = collapse_intra_expert_duplicates([first, second])
    assert len(collapsed) == 2


def test_convergence_merges_same_issue_and_keeps_attribution():
    left = _obs(observation_id="o1", expert_id="frank", expert_label="Frank")
    right = _obs(
        observation_id="o2",
        expert_id="roger",
        expert_label="Roger",
        issue="The document authors request that the decision be annulled.",
        recommended_action="From the user's perspective, test whether the request holds.",
    )
    comments = apply_word_comment_convergence(
        [left, right],
        WordCommentConvergence(issues=[_issue()]),
    )
    assert len(comments) == 1
    assert comments[0].supporting_expert_ids == ("frank", "roger")
    assert "your request" not in comments[0].kommentar.casefold()
    assert "document authors" in comments[0].kommentar


def test_convergence_does_not_merge_different_issues():
    left = _obs(observation_id="o1", issue="Missing limitation period.")
    right = _obs(
        observation_id="o2",
        expert_id="roger",
        expert_label="Roger",
        issue="Unspecified costs in the prayer.",
        recommended_action="Ask for a breakdown.",
    )
    comments = apply_word_comment_convergence(
        [left, right],
        WordCommentConvergence(
            issues=[
                _issue(
                    short_comment=(
                        "Missing limitation and unspecified costs should both be "
                        "fixed in one long comment that also discusses strategy."
                    )
                )
            ]
        ),
    )
    assert len(comments) == 2
    texts = {item.kommentar for item in comments}
    assert any("limitation" in text.casefold() for text in texts)
    assert any("cost" in text.casefold() for text in texts)


def test_convergence_rejects_long_or_misattributed_short_comment():
    observation = _obs()
    long_text = " ".join(["This comment restates every argument on both sides."] * 25)
    assert comment_exceeds_soft_cap(long_text)
    long_comments = apply_word_comment_convergence(
        [observation],
        WordCommentConvergence(
            issues=[
                _issue(
                    observation_ids=["o1"],
                    supporting_expert_ids=["frank"],
                    short_comment=long_text,
                )
            ]
        ),
    )
    assert len(long_comments) == 1
    assert long_comments[0].kommentar != long_text
    assert not comment_exceeds_soft_cap(long_comments[0].kommentar)

    flipped = apply_word_comment_convergence(
        [observation],
        WordCommentConvergence(
            issues=[
                _issue(
                    observation_ids=["o1"],
                    supporting_expert_ids=["frank"],
                    short_comment="Your request is correctly limited.",
                )
            ]
        ),
    )
    assert "your request" not in flipped[0].kommentar.casefold()
    assert "document authors" in flipped[0].kommentar.casefold()


def test_prompts_require_atomic_attributed_observations():
    sv = default_prompts("sv")
    comment = sv["expertgranskning.word.expert.comment"]
    convergence = sv["expertgranskning.word.comment_convergence"]
    moderator = sv["expertgranskning.word.moderator.batch"]
    assert "EN sakfråga" in comment
    assert "statement_owner" in comment
    assert "recommendation_recipient" in comment
    assert "your claim" in comment
    assert "Leverantören" not in comment
    assert "EN sakfråga" in moderator or "EN materiell sakfråga" in moderator
    assert "väsentligt identiska" in convergence
    assert "statement_owner" in convergence
    en = default_prompts("en")
    assert "ONE issue" in en["expertgranskning.word.expert.comment"]
    assert "Merge only substantially identical issues" in en[
        "expertgranskning.word.comment_convergence"
    ]


def test_timing_counters_are_low_cardinality():
    timings = WordReviewTimings()
    timings.record_comment_generated(over_soft_length=False)
    timings.record_comment_generated(over_soft_length=True)
    timings.record_observations_split(3)
    snapshot = timings.snapshot()
    assert snapshot["comments_generated"] == 2
    assert snapshot["comments_over_soft_length"] == 1
    assert snapshot["observations_split"] == 1
    dumped = repr(snapshot)
    assert "claim" not in dumped
    assert "request" not in dumped
    assert "comment text" not in dumped
