"""Deterministic ownership for progressive Word publication units."""

from __future__ import annotations

from app.services.expertgranskning.comment_convergence import (
    WordConsolidatedComment,
    WordObservation,
)
from app.services.expertgranskning.schemas import (
    WordDocumentParagraph,
    WordDocumentSection,
)
from app.services.expertgranskning.word_review import (
    build_batches,
    publication_unit_total,
)
from app.services.expertgranskning.word_review_units import (
    batch_owned_indexes,
    leftover_observations,
    partition_owned_comments,
)


def _comment(**overrides) -> WordConsolidatedComment:
    values = {
        "expert_id": "frank",
        "expert_namn": "Frank",
        "supporting_expert_ids": ("frank",),
        "supporting_expert_labels": ("Frank",),
        "paragraph_index": 4,
        "kommentar": "Skärp formuleringen.",
        "observation_ids": ("b0o1",),
    }
    values.update(overrides)
    return WordConsolidatedComment(**values)


def _obs(**overrides) -> WordObservation:
    values = {
        "observation_id": "b0o1",
        "expert_id": "frank",
        "expert_label": "Frank",
        "question_id": "q1",
        "paragraph_index": 4,
        "paragraph_text": "Tidsallokering för uppdraget regleras i ingressen.",
        "list_string": "",
        "kommentar": "Tidsallokeringen är otydlig.",
    }
    values.update(overrides)
    return WordObservation(**values)


def test_publication_unit_total_counts_batches_and_heading():
    paragraphs = [
        WordDocumentParagraph(
            index=index,
            text=f"Stycke {index} är tillräckligt långt för granskning.",
            style="Normal",
        )
        for index in range(1, 10)
    ]
    section = WordDocumentSection(
        heading="Avtal",
        heading_style="Heading 1",
        heading_paragraph_index=0,
        paragraphs=paragraphs,
    )
    assert [len(batch) for batch in build_batches(section)] == [4, 4, 1]
    assert publication_unit_total([section], None) == 4


def test_partition_owned_comments_consumes_merged_lookahead_ids():
    owned = batch_owned_indexes(
        [
            WordDocumentParagraph(index=1, text="a", style="Normal"),
            WordDocumentParagraph(index=2, text="b", style="Normal"),
            WordDocumentParagraph(index=3, text="c", style="Normal"),
            WordDocumentParagraph(index=4, text="d", style="Normal"),
        ]
    )
    published, consumed = partition_owned_comments(
        [
            _comment(
                paragraph_index=4,
                observation_ids=("b0o1", "b1o1"),
            ),
            _comment(
                paragraph_index=5,
                observation_ids=("b1o2",),
                expert_id="roger",
            ),
        ],
        owned,
    )
    assert [item.paragraph_index for item in published] == [4]
    assert consumed == frozenset({"b0o1", "b1o1"})
    leftover = leftover_observations(
        [
            _obs(observation_id="b0o1", paragraph_index=4),
            _obs(observation_id="b1o1", paragraph_index=5),
            _obs(observation_id="b1o2", paragraph_index=5, expert_id="roger"),
        ],
        consumed,
    )
    assert [item.observation_id for item in leftover] == ["b1o2"]


def test_partition_owned_comments_holds_later_batch_anchor():
    owned = frozenset({1, 2, 3, 4})
    published, consumed = partition_owned_comments(
        [
            _comment(
                paragraph_index=5,
                observation_ids=("b0o1", "b1o1"),
            )
        ],
        owned,
    )
    assert published == []
    assert consumed == frozenset()
    leftover = leftover_observations(
        [
            _obs(observation_id="b0o1", paragraph_index=4),
            _obs(observation_id="b1o1", paragraph_index=5),
        ],
        consumed,
    )
    assert [item.observation_id for item in leftover] == ["b0o1", "b1o1"]
