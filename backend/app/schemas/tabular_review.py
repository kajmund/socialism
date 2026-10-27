"""HTTP contracts for SSR Tabular Review."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.services.tabular_review.types import DEFAULT_SCORE_THRESHOLD

CellStatus = Literal["hit", "no_hit", "unknown", "negative_hit"]
CellPolarity = Literal["positive", "negative"]
ReviewState = Literal["pending", "approved", "rejected"]
LabelVerdict = Literal["match", "not_match"]


class TabularReviewColumnWrite(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    anchor_set_id: str
    label: str = Field(min_length=1, max_length=64)
    polarity: CellPolarity = "positive"
    allow_abstain: bool = False
    abstain_margin: float | None = None


class TabularReviewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    document_ids: list[str] = Field(default_factory=list)
    columns: list[TabularReviewColumnWrite] = Field(default_factory=list)
    score_threshold: float = DEFAULT_SCORE_THRESHOLD


class TabularReviewUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    document_ids: list[str] | None = None
    score_threshold: float | None = None
    sort_key: str | None = None
    sort_dir: Literal["asc", "desc"] | None = None
    filter_json: dict | None = None


class TabularReviewColumnOut(BaseModel):
    id: int
    title: str
    anchor_set_id: str
    label: str
    polarity: CellPolarity
    allow_abstain: bool
    abstain_margin: float | None
    sort_order: int


class TabularReviewCandidateOut(BaseModel):
    rank: int
    text_unit_id: str
    exact_text: str
    similarity: float
    polarity: CellPolarity
    source: dict


class TabularReviewCellOut(BaseModel):
    id: int
    row_id: int
    column_id: int
    status: CellStatus
    similarity: float | None
    text_unit_id: str | None
    exact_text: str | None
    source: dict
    locked: bool
    flagged: bool
    review_state: ReviewState
    note: str | None
    candidate_count: int
    candidates: list[TabularReviewCandidateOut] = Field(default_factory=list)


class TabularReviewRowOut(BaseModel):
    id: int
    document_id: str
    document_version_id: str
    title: str
    source_object_id: str | None
    cells: list[TabularReviewCellOut]


class TabularReviewSummaryOut(BaseModel):
    id: int
    name: str
    document_count: int
    column_count: int
    score_threshold: float
    computed_at: str | None
    updated_at: str
    created_at: str


class TabularReviewOut(BaseModel):
    id: int
    name: str
    customer_id: int
    score_threshold: float
    sort_key: str
    sort_dir: str
    filter_json: dict
    computed_at: str | None
    updated_at: str
    created_at: str
    columns: list[TabularReviewColumnOut]
    rows: list[TabularReviewRowOut]


class TabularReviewDocumentOut(BaseModel):
    document_id: str
    title: str
    document_version_id: str
    source_object_id: str | None
    mime_type: str


class TabularReviewCellAction(BaseModel):
    note: str | None = None


class TabularReviewEventOut(BaseModel):
    id: int
    action: str
    actor_user_id: str
    payload: dict
    created_at: str


class TabularReviewLabelOut(BaseModel):
    id: int
    label: str
    anchor_set_id: str
    text_unit_id: str
    verdict: LabelVerdict
    activated_as_ssr_anchor: bool
    created_at: str
