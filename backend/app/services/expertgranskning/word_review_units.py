"""Stable publication units below Heading-1 section scope.

Comment windows look one batch ahead so nearby cross-batch duplicates can
collapse. Ownership is deterministic: a comment is materialized by the
batch that owns its paragraph, and each observation is consumed once.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.services.expertgranskning.comment_convergence import (
    WordConsolidatedComment,
    WordObservation,
)
from app.services.expertgranskning.schemas import (
    WordDocumentParagraph,
    WordHeadingAssessment,
    WordRewriteSuggestion,
)


@dataclass(frozen=True)
class WordPublicationUnit:
    section_index: int
    comments: list[WordConsolidatedComment] = field(default_factory=list)
    rewrites: list[tuple[WordDocumentParagraph, WordRewriteSuggestion]] = field(
        default_factory=list
    )
    heading: WordHeadingAssessment | None = None
    completes_unit: bool = True


@dataclass(frozen=True)
class WordSectionStats:
    section_index: int
    paragraph_reviews: int
    heading_reviews: int


@dataclass(frozen=True)
class WordSectionDone:
    stats: WordSectionStats


@dataclass(frozen=True)
class WordSectionFailed:
    section_index: int
    error: BaseException


def batch_owned_indexes(
    paragraphs: Sequence[WordDocumentParagraph],
) -> frozenset[int]:
    return frozenset(paragraph.index for paragraph in paragraphs)


def partition_owned_comments(
    comments: Sequence[WordConsolidatedComment],
    owned_indexes: frozenset[int],
) -> tuple[list[WordConsolidatedComment], frozenset[str]]:
    """Keep comments anchored in this batch; return consumed observation ids."""
    owned = [
        item for item in comments if item.paragraph_index in owned_indexes
    ]
    consumed = frozenset(
        observation_id
        for item in owned
        for observation_id in item.observation_ids
    )
    return owned, consumed


def leftover_observations(
    collapsed: Sequence[WordObservation],
    consumed_ids: frozenset[str],
) -> list[WordObservation]:
    return [item for item in collapsed if item.observation_id not in consumed_ids]
