"""WordTask contract: fail closed on unknown types and invalid selection scope."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.expertgranskning.schemas import (
    ExpertgranskningWordJobCreate,
    ExpertgranskningWordJobRequest,
)
from app.services.word.tasks import (
    WordTask,
    paragraph_is_actionable,
    require_review_panel_task,
    selection_target_indexes,
    snapshot_indexes_from_sections,
    validate_word_task_against_sections,
)
from tests.test_expertgranskning_word_review import _review_task


def _sections(*indexes: int) -> list[dict]:
    heading, *body = indexes or (0,)
    return [
        {
            "heading": "Avtal",
            "heading_style": "Heading 1",
            "heading_paragraph_index": heading,
            "paragraphs": [
                {
                    "index": index,
                    "text": f"Detta stycke {index} är tillräckligt långt.",
                    "style": "Normal",
                }
                for index in body
            ],
        }
    ]


def test_review_document_panel_validates():
    task = WordTask.model_validate(_review_task(12))
    assert task.task_type == "review"
    assert task.scope.type == "document"
    assert task.expert_strategy.type == "panel"
    assert task.expert_strategy.panel_id == 12
    assert selection_target_indexes(task) is None


def test_review_selection_panel_validates_and_sorts():
    task = WordTask.model_validate(
        _review_task(12, paragraph_indexes=[16, 14, 15])
    )
    assert task.scope.type == "selection"
    assert task.scope.paragraph_indexes == [14, 15, 16]
    assert selection_target_indexes(task) == frozenset({14, 15, 16})


def test_unknown_task_type_fails():
    with pytest.raises(ValidationError, match="task_type"):
        WordTask.model_validate(
            {
                "task_type": "improve",
                "scope": {"type": "document"},
                "expert_strategy": {"type": "panel", "panel_id": 1},
            }
        )


def test_unknown_expert_strategy_fails():
    with pytest.raises(ValidationError):
        WordTask.model_validate(
            {
                "task_type": "review",
                "scope": {"type": "document"},
                "expert_strategy": {"type": "library", "panel_id": 1},
            }
        )


def test_empty_selection_fails():
    with pytest.raises(ValidationError):
        WordTask.model_validate(_review_task(1, paragraph_indexes=[]))


def test_duplicate_indexes_fail():
    with pytest.raises(ValidationError, match="unique"):
        WordTask.model_validate(_review_task(1, paragraph_indexes=[14, 14, 15]))


def test_document_scope_rejects_selection_indexes():
    with pytest.raises(ValidationError, match="paragraph_indexes"):
        WordTask.model_validate(
            {
                "task_type": "review",
                "scope": {"type": "document", "paragraph_indexes": [1]},
                "expert_strategy": {"type": "panel", "panel_id": 1},
            }
        )


def test_nonexistent_index_fails_against_snapshot():
    task = WordTask.model_validate(_review_task(1, paragraph_indexes=[14, 99]))
    sections = ExpertgranskningWordJobCreate.model_validate(
        {
            "task": _review_task(),
            "sections": _sections(0, 14, 15, 16),
        }
    ).sections
    with pytest.raises(ValueError, match="not in snapshot"):
        validate_word_task_against_sections(task, sections)


def test_create_rejects_index_missing_from_snapshot():
    with pytest.raises(ValidationError, match="not in snapshot"):
        ExpertgranskningWordJobCreate.model_validate(
            {
                "task": _review_task(1, paragraph_indexes=[14, 99]),
                "sections": _sections(0, 14, 15, 16),
            }
        )


def test_job_request_stores_full_word_task():
    request = ExpertgranskningWordJobRequest.model_validate(
        {
            "customer_id": 1,
            "owner_user_id": "u1",
            "doc_id": "doc-1",
            "word_session_id": "sess-1",
            "locale": "sv",
            "review_intent": "Devbrains är motpart i avtalet.",
            "task": _review_task(12, paragraph_indexes=[14, 15, 16]),
            "sections": _sections(0, 14, 15, 16),
        }
    )
    dumped = request.model_dump(mode="json")
    assert dumped["task"] == {
        "task_type": "review",
        "scope": {"type": "selection", "paragraph_indexes": [14, 15, 16]},
        "expert_strategy": {"type": "panel", "panel_id": 12},
    }
    assert dumped["review_intent"] == "Devbrains är motpart i avtalet."
    assert "panel_id" not in dumped
    assert request.panel_id == 12
    assert snapshot_indexes_from_sections(request.sections) == {0, 14, 15, 16}


def test_create_rejects_legacy_top_level_panel_id():
    with pytest.raises(ValidationError):
        ExpertgranskningWordJobCreate.model_validate(
            {
                "panel_id": 1,
                "sections": _sections(0, 1),
            }
        )


def test_require_review_panel_task_returns_panel():
    task = WordTask.model_validate(_review_task(4))
    assert require_review_panel_task(task).panel_id == 4


def test_paragraph_is_actionable_uses_frozen_selection():
    request = {
        "task": _review_task(1, paragraph_indexes=[14, 15]),
        "sections": _sections(0, 14, 15, 16),
    }
    assert paragraph_is_actionable(request, 14)
    assert not paragraph_is_actionable(request, 16)
    assert paragraph_is_actionable({"task": _review_task()}, 16)
    assert not paragraph_is_actionable(None, 16)
    assert not paragraph_is_actionable({}, 16)
    assert not paragraph_is_actionable({"sections": []}, 16)
    assert not paragraph_is_actionable(
        {
            "task": {
                "task_type": "improve",
                "scope": {"type": "document"},
                "expert_strategy": {"type": "panel", "panel_id": 1},
            }
        },
        16,
    )
