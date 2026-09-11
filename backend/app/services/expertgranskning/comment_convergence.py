"""Consolidate overlapping Word-review observations before comments are written.

Deduplicates issues, not experts. Intra-expert near-duplicates collapse in
code. Inter-expert grouping is a structured LLM step; actual dissensus is
never dropped.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.expertgranskning.schemas import (
    WordCommentConvergence,
    WordConvergedIssue,
)

NEARBY_PARAGRAPH_DISTANCE = 1
SIMILAR_COMMENT_JACCARD = 0.45

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


@dataclass(frozen=True)
class WordConsolidatedComment:
    expert_id: str
    expert_namn: str
    supporting_expert_ids: tuple[str, ...]
    supporting_expert_labels: tuple[str, ...]
    paragraph_index: int
    kommentar: str


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
        f"kommentar: {observation.kommentar}"
    )


def format_observations_for_prompt(observations: Sequence[WordObservation]) -> str:
    return "\n\n".join(format_observation_block(observation) for observation in observations)


def _collapse_cluster(cluster: list[WordObservation]) -> WordObservation:
    anchor = choose_specific_anchor(cluster)
    richest = max(cluster, key=lambda item: len(item.kommentar.strip()))
    return WordObservation(
        observation_id=cluster[0].observation_id,
        expert_id=cluster[0].expert_id,
        expert_label=cluster[0].expert_label,
        question_id=anchor.question_id,
        paragraph_index=anchor.paragraph_index,
        paragraph_text=anchor.paragraph_text,
        list_string=anchor.list_string,
        kommentar=richest.kommentar,
    )


def _intra_expert_linked(left: WordObservation, right: WordObservation) -> bool:
    if left.expert_id != right.expert_id:
        return False
    if left.question_id == right.question_id:
        return True
    return observations_are_nearby(left, right) and comments_are_similar(
        left.kommentar, right.kommentar
    )


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


def consolidated_from_observation(observation: WordObservation) -> WordConsolidatedComment:
    return WordConsolidatedComment(
        expert_id=observation.expert_id,
        expert_namn=observation.expert_label,
        supporting_expert_ids=(observation.expert_id,),
        supporting_expert_labels=(observation.expert_label,),
        paragraph_index=observation.paragraph_index,
        kommentar=observation.kommentar,
    )


def _comment_from_members(
    members: Sequence[WordObservation],
    *,
    paragraph_index: int | None,
    kommentar: str,
    supporting_expert_ids: Sequence[str],
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
    text = kommentar.strip() or max(members, key=lambda item: len(item.kommentar)).kommentar
    return WordConsolidatedComment(
        expert_id=ids[0],
        expert_namn=format_supporting_labels(labels),
        supporting_expert_ids=ids,
        supporting_expert_labels=labels,
        paragraph_index=anchor_index,
        kommentar=text,
    )


def _split_dissenting_members(
    members: Sequence[WordObservation],
) -> list[list[WordObservation]]:
    by_expert: dict[str, list[WordObservation]] = {}
    for item in members:
        by_expert.setdefault(item.expert_id, []).append(item)
    return list(by_expert.values())


def apply_word_comment_convergence(
    observations: Sequence[WordObservation],
    parsed: WordCommentConvergence,
) -> list[WordConsolidatedComment]:
    """Apply an LLM grouping. Dissensus is split; leftover observations stay."""
    by_id = {item.observation_id: item for item in observations}
    assigned: set[str] = set()
    groups: list[tuple[list[WordObservation], WordConvergedIssue | None]] = []

    for issue in parsed.issues:
        members: list[WordObservation] = []
        for raw_id in issue.observation_ids:
            observation = by_id.get(raw_id.strip())
            if observation is None or observation.observation_id in assigned:
                continue
            members.append(observation)
            assigned.add(observation.observation_id)
        if not members:
            continue
        if issue.has_dissensus or comments_dissent([item.kommentar for item in members]):
            for split in _split_dissenting_members(members):
                groups.append((split, None))
            continue
        groups.append((members, issue))

    for observation in observations:
        if observation.observation_id not in assigned:
            groups.append(([observation], None))

    comments: list[WordConsolidatedComment] = []
    for members, issue in groups:
        if issue is None:
            comments.append(
                _comment_from_members(
                    members,
                    paragraph_index=None,
                    kommentar="",
                    supporting_expert_ids=[item.expert_id for item in members],
                )
            )
            continue
        comments.append(
            _comment_from_members(
                members,
                paragraph_index=issue.paragraph_index,
                kommentar=issue.kommentar,
                supporting_expert_ids=issue.supporting_expert_ids,
            )
        )
    return comments
