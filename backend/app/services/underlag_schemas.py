"""API schemas for personal underlag files."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ExtractionStatus = Literal["pending", "ok", "failed", "empty", "unsupported", "needs_ocr"]
KnowledgeStatus = Literal["pending", "running", "ready", "failed", "empty", "needs_ocr"]
KnowledgeItemKind = Literal["fact", "qa", "bookmark", "note"]
KnowledgeItemStatus = Literal["active", "needs_review", "archived"]
KnowledgeAnchorType = Literal["text", "image", "chart", "table"]


class UnderlagOut(BaseModel):
    id: str
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    module: str
    owner_user_id: str | None = None
    folder_id: str | None = None
    extraction_status: ExtractionStatus | None = None
    extracted_text: str | None = None
    knowledge_status: KnowledgeStatus | None = None
    knowledge_error: str | None = None
    knowledge_job_id: str | None = None
    created_at: str = ""


class UnderlagFolderOut(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    created_at: str = ""


class UnderlagListingOut(BaseModel):
    folder_id: str | None = None
    folders: list[UnderlagFolderOut]
    files: list[UnderlagOut]


class UnderlagFolderCreate(BaseModel):
    module: str
    name: str = Field(min_length=1, max_length=80)
    parent_id: str | None = None


class UnderlagMove(BaseModel):
    folder_id: str | None = None


class DocumentAnchorRect(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class DocumentKnowledgeAnchorWrite(BaseModel):
    anchor_type: KnowledgeAnchorType = "text"
    page_number: int | None = Field(default=None, ge=1)
    locator: str | None = Field(default=None, max_length=128)
    exact_text: str | None = Field(default=None, max_length=12000)
    prefix_text: str | None = Field(default=None, max_length=1000)
    suffix_text: str | None = Field(default=None, max_length=1000)
    rects: list[DocumentAnchorRect] = Field(default_factory=list, max_length=100)
    asset_id: str | None = Field(default=None, max_length=64)

    @field_validator("locator", "exact_text", "prefix_text", "suffix_text", "asset_id")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        cleaned = " ".join((value or "").split())
        return cleaned or None

    @model_validator(mode="after")
    def validate_text_anchor(self):
        if self.anchor_type == "text" and not self.exact_text:
            raise ValueError("text anchors require exact_text")
        if self.page_number is None and not self.locator:
            raise ValueError("anchors require page_number or locator")
        return self


class DocumentKnowledgeAnchorOut(DocumentKnowledgeAnchorWrite):
    id: str
    ordinal: int


class DocumentKnowledgeItemWrite(BaseModel):
    kind: KnowledgeItemKind
    title: str = Field(min_length=1, max_length=500)
    question: str | None = Field(default=None, max_length=4000)
    content: str | None = Field(default=None, max_length=12000)
    anchors: list[DocumentKnowledgeAnchorWrite] = Field(min_length=1, max_length=20)

    @field_validator("title", "question", "content")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @model_validator(mode="after")
    def validate_kind_shape(self):
        if self.kind == "qa":
            if not self.question or not self.content:
                raise ValueError("qa requires question and content")
        elif self.kind == "fact" and not self.content:
            raise ValueError("fact requires content")
        elif self.kind == "note" and not self.content:
            raise ValueError("note requires content")
        elif self.kind == "bookmark" and self.question:
            raise ValueError("bookmark cannot have a question")
        return self


class DocumentKnowledgeItemUpdate(BaseModel):
    kind: KnowledgeItemKind
    title: str = Field(min_length=1, max_length=500)
    question: str | None = Field(default=None, max_length=4000)
    content: str | None = Field(default=None, max_length=12000)
    anchors: list[DocumentKnowledgeAnchorWrite] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_shape(self):
        DocumentKnowledgeItemWrite.model_validate(self.model_dump())
        return self


class DocumentKnowledgeItemOut(BaseModel):
    id: str
    source_object_id: str
    kind: KnowledgeItemKind
    origin: Literal["generated", "manual"]
    status: KnowledgeItemStatus
    title: str
    question: str | None = None
    content: str | None = None
    retrieval_queries: list[str] = Field(default_factory=list)
    anchors: list[DocumentKnowledgeAnchorOut] = Field(default_factory=list)
    revision: int
    created_by_user_id: str | None = None
    updated_by_user_id: str | None = None
    created_at: str
    updated_at: str
