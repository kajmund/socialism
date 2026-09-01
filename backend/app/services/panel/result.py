"""Shared panel result envelope. Methods write this; DD reports adapt to DdPanelResult."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.panel.schemas import DdPanelResult


class PanelClaim(BaseModel):
    claim_id: str
    claim: str
    evidence: str
    judgment: str
    score: int | None = None
    dissensus: bool = False


class PanelResult(BaseModel):
    schema_version: Literal["1"] = "1"
    protocol: str
    summary: str
    claims: list[PanelClaim] = Field(default_factory=list)
    unanswered: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


def is_panel_result_envelope(data: dict[str, Any]) -> bool:
    return data.get("schema_version") == "1" and "payload" in data and "claims" in data


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
