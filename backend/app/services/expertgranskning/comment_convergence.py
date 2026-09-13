"""Consolidate overlapping Word-review observations before comments are written.

Deduplicates issues, not experts. Intra-expert near-duplicates collapse in
code. Inter-expert grouping is a structured LLM step; actual dissensus is
never dropped.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.expertgranskning.observation import (
    comment_exceeds_soft_cap,
    comment_misattributes_user_claim,
    issue_text_for_match,
    materialize_word_comment,
)
from app.services.expertgranskning.schemas import (
    WordCommentConvergence,
    WordConvergedIssue,
    WordLlmConvergedIssue,
)

logger = logging.getLogger(__name__)

DEFAULT_ISSUE_MATERIALITY = "medium"
DEFAULT_ISSUE_ACTIONABILITY = "actionable"
DEFAULT_ISSUE_NOVELTY = "new"
DEFAULT_ISSUE_SHOULD_MATERIALIZE = True

NEARBY_PARAGRAPH_DISTANCE = 1
SIMILAR_COMMENT_JACCARD = 0.45
# Live 12-observation chunks truncated around 26k JSON chars (~max_tokens).
COMMENT_CONVERGENCE_CHUNK_SIZE = 4
COMMENT_CONVERGENCE_CHUNK_HARD_CAP = 6
COMMENT_CONVERGENCE_CHUNK_MAX_CHARS = 3500

_TOKEN_RE = re.compile(r"[0-9a-zåäöé]+", re.IGNORECASE)
_ACCEPT_MARKERS = (
    "acceptabel",
    "godtagbar",
    "godtagbart",
    "rimlig",
    "i huvudsak ok",
    "behöver inte ändras",
    "kan godtas",
    "inget att invända",
    "acceptable",
)
_REJECT_MARKERS = (
    "sänk",
    "sänkas",
    "sänkning",
    "för hög",
    "för högt",
    "oacceptabel",
    "bör ändras",
    "bör sänkas",
    "rekommenderar sänkning",
    "alltför",
    "too high",
    "should be lowered",
)
_NEGATIONS = ("inte ", "icke ", "ej ", "not ")


@dataclass(frozen=True)
class WordObservation:
    observation_id: str
    expert_id: str
    expert_label: str
    question_id: str
    paragraph_index: int
    paragraph_text: str
    list_string: str
    kommentar: str
    issue: str = ""
    analysis: str = ""
    source_perspective: str = ""
    target_perspective: str = ""
    statement_owner: str = ""
    recommendation_recipient: str = ""
    consequence: str = ""
    recommended_action: str = ""

    def issue_match_text(self) -> str:
        return issue_text_for_match(issue=self.issue, kommentar=self.kommentar)


@dataclass(frozen=True)
class WordConsolidatedComment:
    expert_id: str
    expert_namn: str
    supporting_expert_ids: tuple[str, ...]
    supporting_expert_labels: tuple[str, ...]
    paragraph_index: int
    kommentar: str
    explanation: str = ""
    should_materialize: bool = True
    has_dissensus: bool = False
    observation_ids: tuple[str, ...] = ()


def comment_tokens(text: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(text.casefold()))


def token_jaccard(left: str, right: str) -> float:
    left_tokens = comment_tokens(left)
    right_tokens = comment_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def comments_are_similar(left: str, right: str) -> bool:
    if left.strip().casefold() == right.strip().casefold():
        return True
    return token_jaccard(left, right) >= SIMILAR_COMMENT_JACCARD


def _has_marker(folded: str, marker: str) -> bool:
    marker_tokens = tuple(_TOKEN_RE.findall(marker))
    if not marker_tokens:
        return False
    if len(marker_tokens) == 1:
        return any(
            token == marker_tokens[0] or token.startswith(marker_tokens[0])
            for token in comment_tokens(folded)
        )
    return marker in folded


def _negated_marker(folded: str, marker: str) -> bool:
    return any(f"{neg}{marker}" in folded for neg in _NEGATIONS)


def _polarity(text: str) -> str | None:
    folded = text.casefold()
    negated_accept = any(_negated_marker(folded, marker) for marker in _ACCEPT_MARKERS)
    negated_reject = any(_negated_marker(folded, marker) for marker in _REJECT_MARKERS)
    has_accept = any(_has_marker(folded, marker) for marker in _ACCEPT_MARKERS)
    has_reject = any(_has_marker(folded, marker) for marker in _REJECT_MARKERS)
    accept = (has_accept and not negated_accept) or negated_reject
    reject = (has_reject and not negated_reject) or negated_accept
    if accept and not reject:
        return "accept"
    if reject and not accept:
        return "reject"
    return None


def comments_dissent(texts: Sequence[str]) -> bool:
    poles = {_polarity(text) for text in texts}
    return "accept" in poles and "reject" in poles


def observations_are_nearby(left: WordObservation, right: WordObservation) -> bool:
    return abs(left.paragraph_index - right.paragraph_index) <= NEARBY_PARAGRAPH_DISTANCE


def choose_specific_anchor(candidates: Sequence[WordObservation]) -> WordObservation:
    """Prefer the most specific clause number, then the later paragraph."""

    def specificity(observation: WordObservation) -> tuple[int, int, int]:
        segments = len(re.findall(r"\d+", observation.list_string))
        return (
            segments,
            observation.paragraph_index,
            len(observation.paragraph_text.strip()),
        )

    return max(candidates, key=specificity)


def _unique_preserving(values: Sequence[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return tuple(seen)


def format_supporting_labels(labels: Sequence[str]) -> str:
    return ", ".join(_unique_preserving(labels))


def format_observation_block(observation: WordObservation) -> str:
    return (
        f"### {observation.observation_id}\n"
        f"expert_id: {observation.expert_id}\n"
        f"expert_namn: {observation.expert_label}\n"
        f"question_id: {observation.question_id}\n"
        f"paragraph_index: {observation.paragraph_index}\n"
        f"list_string: {observation.list_string}\n"
        f"paragraph_text: {observation.paragraph_text}\n"
        f"issue: {observation.issue}\n"
        f"source_perspective: {observation.source_perspective}\n"
        f"target_perspective: {observation.target_perspective}\n"
        f"statement_owner: {observation.statement_owner}\n"
        f"recommendation_recipient: {observation.recommendation_recipient}\n"
        f"consequence: {observation.consequence}\n"
        f"recommended_action: {observation.recommended_action}\n"
        f"kommentar: {observation.kommentar}\n"
        f"analysis: {observation.analysis}"
    )


def format_observations_for_prompt(observations: Sequence[WordObservation]) -> str:
    return "\n\n".join(format_observation_block(observation) for observation in observations)


def serialized_chunk_chars(observations: Sequence[WordObservation]) -> int:
    return len(format_observations_for_prompt(observations))


def nearby_observation_clusters(
    observations: Sequence[WordObservation],
) -> list[list[WordObservation]]:
    """Chain observations whose paragraphs sit next to each other."""
    ordered = sorted(
        observations,
        key=lambda item: (item.paragraph_index, item.observation_id),
    )
    clusters: list[list[WordObservation]] = []
    for item in ordered:
        if clusters and observations_are_nearby(clusters[-1][-1], item):
            clusters[-1].append(item)
        else:
            clusters.append([item])
    return clusters


def _chunk_exceeds_budget(
    observations: Sequence[WordObservation],
    *,
    max_size: int,
    max_chars: int,
) -> bool:
    return len(observations) > max_size or serialized_chunk_chars(observations) > max_chars


def _split_cluster_for_budget(
    cluster: Sequence[WordObservation],
    *,
    hard_cap: int,
    max_chars: int,
) -> list[list[WordObservation]]:
    """Keep nearby items together until count or serialized size overflows."""
    pieces: list[list[WordObservation]] = []
    current: list[WordObservation] = []
    for item in cluster:
        candidate = [*current, item]
        if current and _chunk_exceeds_budget(
            candidate, max_size=hard_cap, max_chars=max_chars
        ):
            pieces.append(current)
            current = [item]
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk_observations_for_convergence(
    observations: Sequence[WordObservation],
    *,
    max_size: int = COMMENT_CONVERGENCE_CHUNK_SIZE,
    hard_cap: int = COMMENT_CONVERGENCE_CHUNK_HARD_CAP,
    max_chars: int = COMMENT_CONVERGENCE_CHUNK_MAX_CHARS,
) -> list[list[WordObservation]]:
    """Pack nearby clusters without overflowing the convergence output budget.

    A nearby cluster may overflow max_size so adjacent paragraphs stay
    together, but never past hard_cap or max_chars. A single oversized
    observation stays alone. Every observation is kept exactly once, in
    deterministic order.
    """
    if max_size < 1:
        raise ValueError("comment-convergence chunk size must be >= 1")
    if hard_cap < max_size:
        raise ValueError("comment-convergence hard cap must be >= chunk size")
    if max_chars < 1:
        raise ValueError("comment-convergence char budget must be >= 1")
    chunks: list[list[WordObservation]] = []
    current: list[WordObservation] = []
    for cluster in nearby_observation_clusters(observations):
        for piece in _split_cluster_for_budget(
            cluster, hard_cap=hard_cap, max_chars=max_chars
        ):
            if current and _chunk_exceeds_budget(
                [*current, *piece], max_size=max_size, max_chars=max_chars
            ):
                chunks.append(current)
                current = []
            current.extend(piece)
    if current:
        chunks.append(current)
    return chunks


def paragraph_indexes_for_observations(
    observations: Sequence[WordObservation],
) -> set[int]:
    return {item.paragraph_index for item in observations}


def observations_are_same_issue(left: WordObservation, right: WordObservation) -> bool:
    return comments_are_similar(left.issue_match_text(), right.issue_match_text())


def structured_issues_conflict(members: Sequence[WordObservation]) -> bool:
    issues = [item.issue.strip() for item in members if item.issue.strip()]
    if len(issues) < 2:
        return False
    seed = issues[0]
    return any(not comments_are_similar(seed, item) for item in issues[1:])


def _copy_observation(
    source: WordObservation,
    *,
    observation_id: str,
    expert_id: str,
    expert_label: str,
    question_id: str,
    paragraph_index: int,
    paragraph_text: str,
    list_string: str,
) -> WordObservation:
    return WordObservation(
        observation_id=observation_id,
        expert_id=expert_id,
        expert_label=expert_label,
        question_id=question_id,
        paragraph_index=paragraph_index,
        paragraph_text=paragraph_text,
        list_string=list_string,
        kommentar=source.kommentar,
        issue=source.issue,
        analysis=source.analysis,
        source_perspective=source.source_perspective,
        target_perspective=source.target_perspective,
        statement_owner=source.statement_owner,
        recommendation_recipient=source.recommendation_recipient,
        consequence=source.consequence,
        recommended_action=source.recommended_action,
    )


def _collapse_cluster(cluster: list[WordObservation]) -> WordObservation:
    anchor = choose_specific_anchor(cluster)
    richest = max(
        cluster,
        key=lambda item: (
            len(item.issue.strip()),
            len(item.analysis.strip()),
            len(item.kommentar.strip()),
        ),
    )
    return _copy_observation(
        richest,
        observation_id=cluster[0].observation_id,
        expert_id=cluster[0].expert_id,
        expert_label=cluster[0].expert_label,
        question_id=anchor.question_id,
        paragraph_index=anchor.paragraph_index,
        paragraph_text=anchor.paragraph_text,
        list_string=anchor.list_string,
    )


def _intra_expert_linked(left: WordObservation, right: WordObservation) -> bool:
    if left.expert_id != right.expert_id:
        return False
    if not observations_are_same_issue(left, right):
        return False
    if left.question_id == right.question_id:
        return True
    return observations_are_nearby(left, right)


def collapse_intra_expert_duplicates(
    observations: Sequence[WordObservation],
) -> list[WordObservation]:
    """One comment per expert per issue; keep the most specific nearby anchor."""
    pending = list(observations)
    collapsed: list[WordObservation] = []
    while pending:
        seed = pending.pop(0)
        cluster = [seed]
        changed = True
        while changed:
            changed = False
            remaining: list[WordObservation] = []
            for candidate in pending:
                if any(_intra_expert_linked(item, candidate) for item in cluster):
                    cluster.append(candidate)
                    changed = True
                else:
                    remaining.append(candidate)
            pending = remaining
        collapsed.append(_collapse_cluster(cluster))
    return collapsed


def decide_word_issue_materialization(issue: WordConvergedIssue) -> bool:
    """Explicit surfacing contract. Dissensus is never filtered as overlap."""
    if issue.has_dissensus:
        return True
    if issue.novelty == "overlap":
        return False
    if issue.materiality == "low" and issue.actionability == "informational":
        return False
    return issue.should_materialize


def finalize_word_converged_issue(
    raw: WordLlmConvergedIssue | WordConvergedIssue,
) -> tuple[WordConvergedIssue, int]:
    """Fill missing classification fields so a valid issue still surfaces."""
    if isinstance(raw, WordConvergedIssue):
        return raw, 0
    fallbacks = 0
    materiality = raw.materiality
    if materiality is None:
        materiality = DEFAULT_ISSUE_MATERIALITY
        fallbacks += 1
    actionability = raw.actionability
    if actionability is None:
        actionability = DEFAULT_ISSUE_ACTIONABILITY
        fallbacks += 1
    novelty = raw.novelty
    if novelty is None:
        novelty = DEFAULT_ISSUE_NOVELTY
        fallbacks += 1
    should_materialize = raw.should_materialize
    if should_materialize is None:
        should_materialize = DEFAULT_ISSUE_SHOULD_MATERIALIZE
        fallbacks += 1
    return (
        WordConvergedIssue(
            observation_ids=raw.observation_ids,
            paragraph_index=raw.paragraph_index,
            supporting_expert_ids=raw.supporting_expert_ids,
            short_comment=raw.short_comment,
            explanation=raw.explanation,
            materiality=materiality,
            actionability=actionability,
            novelty=novelty,
            should_materialize=should_materialize,
            has_dissensus=raw.has_dissensus,
        ),
        fallbacks,
    )


def finalize_word_comment_convergence(
    parsed: WordCommentConvergence,
) -> WordCommentConvergence:
    """Promote LLM issues to the strict domain model. Log fallback counts only."""
    issues: list[WordConvergedIssue] = []
    fallback_fields = 0
    fallback_issues = 0
    for raw in parsed.issues:
        issue, count = finalize_word_converged_issue(raw)
        issues.append(issue)
        fallback_fields += count
        if count:
            fallback_issues += 1
    if fallback_fields:
        logger.info(
            "Word comment convergence classification fallbacks issues=%s fields=%s",
            fallback_issues,
            fallback_fields,
        )
    return WordCommentConvergence(issues=issues)


def observation_visible_comment(observation: WordObservation) -> str:
    return (
        materialize_word_comment(
            issue=observation.issue,
            consequence=observation.consequence,
            recommended_action=observation.recommended_action,
            kommentar=observation.kommentar,
            statement_owner=observation.statement_owner,
        )
        or observation.kommentar
    )


def consolidated_from_observation(observation: WordObservation) -> WordConsolidatedComment:
    return WordConsolidatedComment(
        expert_id=observation.expert_id,
        expert_namn=observation.expert_label,
        supporting_expert_ids=(observation.expert_id,),
        supporting_expert_labels=(observation.expert_label,),
        paragraph_index=observation.paragraph_index,
        kommentar=observation_visible_comment(observation),
        explanation=observation.analysis.strip(),
        should_materialize=True,
        has_dissensus=False,
        observation_ids=(observation.observation_id,),
    )


def _comment_from_members(
    members: Sequence[WordObservation],
    *,
    paragraph_index: int | None,
    kommentar: str,
    supporting_expert_ids: Sequence[str],
    explanation: str = "",
    should_materialize: bool = True,
    has_dissensus: bool = False,
) -> WordConsolidatedComment:
    labels_by_id = {item.expert_id: item.expert_label for item in members}
    preferred = [item for item in supporting_expert_ids if item in labels_by_id]
    member_ids = [item.expert_id for item in members]
    ids = _unique_preserving([*preferred, *member_ids])
    labels = _unique_preserving(labels_by_id[item] for item in ids)
    allowed = {item.paragraph_index for item in members}
    if paragraph_index in allowed:
        anchor_index = paragraph_index
    else:
        anchor_index = choose_specific_anchor(members).paragraph_index
    primary = max(
        members,
        key=lambda item: (len(item.issue.strip()), len(item.kommentar.strip())),
    )
    text = kommentar.strip() or observation_visible_comment(primary)
    explanation_text = explanation.strip() or primary.analysis.strip()
    return WordConsolidatedComment(
        expert_id=ids[0],
        expert_namn=format_supporting_labels(labels),
        supporting_expert_ids=ids,
        supporting_expert_labels=labels,
        paragraph_index=anchor_index,
        kommentar=text,
        explanation=explanation_text,
        should_materialize=should_materialize,
        has_dissensus=has_dissensus,
        observation_ids=_unique_preserving(
            [item.observation_id for item in members]
        ),
    )


def _split_dissenting_members(
    members: Sequence[WordObservation],
) -> list[list[WordObservation]]:
    by_expert: dict[str, list[WordObservation]] = {}
    for item in members:
        by_expert.setdefault(item.expert_id, []).append(item)
    return list(by_expert.values())


def cluster_equivalent_issues(
    members: Sequence[WordObservation],
) -> list[list[WordObservation]]:
    remaining = list(members)
    clusters: list[list[WordObservation]] = []
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        kept: list[WordObservation] = []
        for item in remaining:
            if observations_are_same_issue(seed, item):
                cluster.append(item)
            else:
                kept.append(item)
        remaining = kept
        clusters.append(cluster)
    return clusters


def _safe_converged_comment(
    members: Sequence[WordObservation],
    issue: WordConvergedIssue,
) -> str:
    """Keep LLM short_comment only when it stays atomic and perspective-safe."""
    primary = members[0]
    short = issue.short_comment.strip()
    if (
        not short
        or comment_exceeds_soft_cap(short)
        or comment_misattributes_user_claim(short, primary.statement_owner)
    ):
        return observation_visible_comment(primary)
    return short


def apply_word_comment_convergence(
    observations: Sequence[WordObservation],
    parsed: WordCommentConvergence,
) -> list[WordConsolidatedComment]:
    """Apply an LLM grouping. Dissensus is split; leftover observations stay."""
    parsed = finalize_word_comment_convergence(parsed)
    by_id = {item.observation_id: item for item in observations}
    assigned: set[str] = set()
    groups: list[tuple[list[WordObservation], WordConvergedIssue | None, bool]] = []

    for raw in parsed.issues:
        issue, _ = finalize_word_converged_issue(raw)
        members: list[WordObservation] = []
        for raw_id in issue.observation_ids:
            observation = by_id.get(raw_id.strip())
            if observation is None or observation.observation_id in assigned:
                continue
            members.append(observation)
            assigned.add(observation.observation_id)
        if not members:
            continue
        dissent_texts = [
            item.kommentar or item.issue or item.recommended_action for item in members
        ]
        if issue.has_dissensus or comments_dissent(dissent_texts):
            for split in _split_dissenting_members(members):
                groups.append((split, None, True))
            continue
        if structured_issues_conflict(members) and comment_exceeds_soft_cap(
            issue.short_comment
        ):
            for cluster in cluster_equivalent_issues(members):
                groups.append((cluster, None, False))
            continue
        groups.append((members, issue, False))

    for observation in observations:
        if observation.observation_id not in assigned:
            groups.append(([observation], None, False))

    comments: list[WordConsolidatedComment] = []
    for members, issue, dissented in groups:
        if issue is None:
            comments.append(
                _comment_from_members(
                    members,
                    paragraph_index=None,
                    kommentar="",
                    supporting_expert_ids=[item.expert_id for item in members],
                    explanation="",
                    should_materialize=True,
                    has_dissensus=dissented,
                )
            )
            continue
        comments.append(
            _comment_from_members(
                members,
                paragraph_index=issue.paragraph_index,
                kommentar=_safe_converged_comment(members, issue),
                supporting_expert_ids=issue.supporting_expert_ids,
                explanation=issue.explanation or members[0].analysis,
                should_materialize=decide_word_issue_materialization(issue),
                has_dissensus=issue.has_dissensus,
            )
        )
    return comments
