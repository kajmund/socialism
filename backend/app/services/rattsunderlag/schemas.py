"""Rättsunderlag result schema. Status is computed in Python, never by the LLM."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.report.rattsutredning import (
    ForarbeteRef,
    LagtextRef,
    PraxisRef,
    RattsutredningPayload,
    SourcingStatus,
)

__all__ = [
    "ForarbeteRef",
    "LagtextRef",
    "PraxisRef",
    "RattsunderlagResearchJobRequest",
    "RattsunderlagResult",
    "RattsunderlagStart",
    "SearchPlan",
    "SourcingStatus",
    "SummaryClaim",
]


class SummaryClaim(BaseModel):
    text: str
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("claim text is required")
        return cleaned


class RattsunderlagResult(RattsutredningPayload):
    claims: list[SummaryClaim] = Field(default_factory=list)
    unanswered: list[str] = Field(default_factory=list)

    def as_payload(self) -> RattsutredningPayload:
        return RattsutredningPayload(
            fraga=self.fraga,
            lagtext=self.lagtext,
            praxis=self.praxis,
            forarbeten=self.forarbeten,
            sammanfattning=self.sammanfattning,
            sourcing_status=self.sourcing_status,
        )


class SearchPlan(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=8)

    @field_validator("queries")
    @classmethod
    def strip_queries(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("at least one search query is required")
        return cleaned


class RattsunderlagStart(BaseModel):
    fraga: str = Field(min_length=1, max_length=8000)
    locale: Literal["sv", "en"] = "sv"

    @field_validator("fraga")
    @classmethod
    def strip_fraga(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("fraga is required")
        return cleaned


class RattsunderlagResearchJobRequest(BaseModel):
    fraga: str
    customer_id: int
    owner_user_id: str
    locale: Literal["sv", "en"] = "sv"
