"""Neutral WordTask contract. Unknown types fail closed."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_WORD_TASK_TYPES = frozenset({"review"})
SUPPORTED_WORD_SCOPE_TYPES = frozenset({"document", "selection"})
SUPPORTED_WORD_EXPERT_STRATEGY_TYPES = frozenset({"panel"})

WordTaskType = Literal["review"]
WordTaskScopeType = Literal["document", "selection"]
WordExpertStrategyType = Literal["panel"]


class WordDocumentScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["document"]

    @model_validator(mode="before")
    @classmethod
    def reject_target_indexes(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("paragraph_indexes"):
            raise ValueError("document scope must not carry paragraph_indexes")
        return value


class WordSelectionScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["selection"]
    paragraph_indexes: list[int] = Field(min_length=1)

    @field_validator("paragraph_indexes")
    @classmethod
    def unique_non_negative_indexes(cls, value: list[int]) -> list[int]:
        if any(index < 0 for index in value):
            raise ValueError("selection paragraph_indexes must be non-negative")
        if len(value) != len(set(value)):
            raise ValueError("selection paragraph_indexes must be unique")
        return sorted(value)


WordTaskScope = Annotated[
    WordDocumentScope | WordSelectionScope,
    Field(discriminator="type"),
]


class WordPanelExpertStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["panel"]
    panel_id: int = Field(gt=0)


WordExpertStrategy = Annotated[
    WordPanelExpertStrategy,
    Field(discriminator="type"),
]


class WordTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: WordTaskType
    scope: WordTaskScope
    expert_strategy: WordExpertStrategy

    @field_validator("task_type")
    @classmethod
    def known_task_type(cls, value: str) -> str:
        if value not in SUPPORTED_WORD_TASK_TYPES:
            raise ValueError(f"unsupported task_type: {value}")
        return value


def require_review_panel_task(task: WordTask) -> WordPanelExpertStrategy:
    if task.task_type != "review":
        raise ValueError(f"unsupported task_type: {task.task_type}")
    strategy = task.expert_strategy
    if strategy.type != "panel":
        raise ValueError(f"unsupported expert_strategy: {strategy.type}")
    return strategy


def snapshot_indexes_from_sections(sections: Sequence[Any]) -> set[int]:
    indexes: set[int] = set()
    for section in sections:
        heading_index = getattr(section, "heading_paragraph_index", None)
        if isinstance(heading_index, int):
            indexes.add(heading_index)
        paragraphs = getattr(section, "paragraphs", None) or []
        for paragraph in paragraphs:
            index = getattr(paragraph, "index", None)
            if isinstance(index, int):
                indexes.add(index)
    return indexes


def validate_word_task_against_sections(task: WordTask, sections: Sequence[Any]) -> None:
    if task.scope.type != "selection":
        return
    known = snapshot_indexes_from_sections(sections)
    missing = [index for index in task.scope.paragraph_indexes if index not in known]
    if missing:
        raise ValueError(
            "selection paragraph_indexes not in snapshot: "
            + ", ".join(str(index) for index in missing)
        )


def selection_target_indexes(task: WordTask) -> frozenset[int] | None:
    """Selected paragraph indexes, or None when the whole document is in scope."""
    if task.scope.type == "document":
        return None
    return frozenset(task.scope.paragraph_indexes)


def task_from_request(request: dict | None) -> WordTask | None:
    if not request:
        return None
    raw = request.get("task")
    if raw is None:
        return None
    return WordTask.model_validate(raw)


def paragraph_is_actionable(request: dict | None, paragraph_index: int) -> bool:
    task = task_from_request(request)
    if task is None:
        return True
    target = selection_target_indexes(task)
    if target is None:
        return True
    return paragraph_index in target
