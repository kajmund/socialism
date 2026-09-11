"""Shared panel result envelope. Methods write this; DD reports adapt to DdPanelResult."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.panel.competency import SlotCompetency
from app.services.panel.schemas import DdPanelResult

PANEL_RESULT_SCHEMA_V1 = "1"
PANEL_RESULT_SCHEMA_V2 = "2"
PANEL_RESULT_SCHEMA_CURRENT = PANEL_RESULT_SCHEMA_V2

UnansweredReason = Literal["missing_expertise"]
MISSING_EXPERTISE_REASON: UnansweredReason = "missing_expertise"


class PanelClaim(BaseModel):
    claim_id: str
    claim: str
    evidence: str
    judgment: str
    score: int | None = None
    dissensus: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class UnansweredItem(BaseModel):
    """Structured gap. ``reason`` is state; ``text`` is presentation only."""

    text: str
    reason: UnansweredReason | None = None


class PanelResult(BaseModel):
    """v2 adds structured unanswered + competency. v1 rows still validate.

    Historical persisted results keep ``unanswered: list[str]``. New writes
    set ``schema_version="2"`` and fill ``unanswered_items`` / ``competency``.
    Missing v2 fields default to empty so old JSON remains readable.
    """

    schema_version: Literal["1", "2"] = PANEL_RESULT_SCHEMA_CURRENT
    protocol: str
    summary: str
    claims: list[PanelClaim] = Field(default_factory=list)
    unanswered: list[str] = Field(default_factory=list)
    unanswered_items: list[UnansweredItem] = Field(default_factory=list)
    competency: list[SlotCompetency] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


def is_panel_result_envelope(data: dict[str, Any]) -> bool:
    return (
        data.get("schema_version") in {PANEL_RESULT_SCHEMA_V1, PANEL_RESULT_SCHEMA_V2}
        and "payload" in data
        and "claims" in data
    )


def envelope_from_dd_panel_result(result: DdPanelResult) -> PanelResult:
    flagged = {note.sub_question_id for note in result.dissensus}
    claims = [
        PanelClaim(
            claim_id=f"{row.expert_slot_id}:{row.sub_question_id}",
            claim=row.sub_question_label,
            evidence=row.motivation,
            judgment=f"{row.score}/10",
            score=row.score,
            dissensus=row.sub_question_id in flagged,
        )
        for row in result.scores
    ]
    return PanelResult(
        schema_version=PANEL_RESULT_SCHEMA_V1,
        protocol="dd_panel",
        summary=result.summary,
        claims=claims,
        unanswered=[note.sub_question_label for note in result.unanswered],
        payload=result.model_dump(mode="json"),
    )


def dd_panel_result_from_stored(data: dict[str, Any]) -> DdPanelResult:
    """Accept envelope (new method) or legacy DdPanelResult dump (dd_engine)."""
    if is_panel_result_envelope(data):
        payload = data["payload"]
        return DdPanelResult.model_validate(
            {
                "protocol": payload.get("protocol") or "dd_panel",
                "candidate": payload["candidate"],
                "scores": payload["scores"],
                "dissensus": payload.get("dissensus") or [],
                "unanswered": payload.get("unanswered") or [],
                "summary": data.get("summary") or payload.get("summary") or "",
            }
        )
    return DdPanelResult.model_validate(data)
