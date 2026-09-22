"""Compact, deterministic Jev state. Never send full document bodies."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.services.research.assessment import AssessableEvidence, review_excerpt
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.planner import ResearchObjective

JEV_EXCERPT_CHARS = 280


@dataclass(frozen=True)
class CompactResearchState:
    payload: dict[str, Any]
    input_chars: int
    input_sha256: str
    evidence_count: int
    clipped_evidence_count: int
    source_types: tuple[str, ...]


def compact_research_state(
    *,
    objective: str,
    plan: ResearchPlan,
    evidence: Sequence[AssessableEvidence],
    runtime_needs: Sequence[RuntimeResearchNeed] | None = None,
    known_gaps: Sequence[str] | None = None,
    known_contradictions: Sequence[str] | None = None,
    max_evidence_items: int,
    max_state_chars: int,
) -> CompactResearchState:
    items = sorted(evidence, key=lambda row: row.evidence_id)
    clipped_count = max(0, len(items) - max_evidence_items)
    kept = items[:max_evidence_items]
    gap_ids = list(known_gaps) if known_gaps is not None else _programmatic_gaps(plan, evidence)
    payload: dict[str, Any] = {
        "objective": objective.strip(),
        "needs": [_need_row(need, evidence) for need in plan.needs],
        "evidence": [_evidence_row(item) for item in kept],
        "known_gaps": [str(item) for item in gap_ids],
        "known_contradictions": [str(item) for item in (known_contradictions or ())],
    }
    if runtime_needs is not None:
        payload["runtime_needs"] = [
            {
                "research_need_id": row.research_need_id,
                "question": row.question,
                "origin": row.origin,
                "wave_number": row.wave_number,
                "source_types": list(row.source_types),
            }
            for row in runtime_needs
        ]
    encoded = _encode(payload)
    if len(encoded) > max_state_chars:
        payload = _shrink_to_budget(payload, max_state_chars)
        encoded = _encode(payload)
        clipped_count = max(clipped_count, len(items) - len(payload.get("evidence") or []))
    source_types = tuple(dict.fromkeys(item.source_type for item in items if item.source_type))
    return CompactResearchState(
        payload=payload,
        input_chars=len(encoded),
        input_sha256=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        evidence_count=len(items),
        clipped_evidence_count=clipped_count,
        source_types=source_types,
    )


def compact_evidence_item_state(
    *,
    objective: str,
    item: AssessableEvidence,
    max_state_chars: int,
) -> tuple[dict[str, Any], int, str]:
    payload = {
        "objective": objective.strip(),
        "evidence": _evidence_row(item),
    }
    encoded = _encode(payload)
    if len(encoded) > max_state_chars:
        row = dict(payload["evidence"])
        row["excerpt"] = review_excerpt(str(row.get("excerpt") or ""), max_chars=120)
        payload = {"objective": objective.strip()[:500], "evidence": row}
        encoded = _encode(payload)
    return payload, len(encoded), hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def found_evidence_ids(need_id: str, evidence: Sequence[AssessableEvidence]) -> list[str]:
    return [
        item.evidence_id
        for item in evidence
        if need_id in (item.research_need_ids or (item.research_need_id,))
        and item.status == "found"
    ]


def _need_row(need: ResearchNeed, evidence: Sequence[AssessableEvidence]) -> dict[str, Any]:
    need_id = need.id
    found = found_evidence_ids(need_id, evidence)
    return {
        "id": need_id,
        "question": need.question,
        "why_needed": need.why_needed,
        "source_types": list(need.source_types),
        "found_evidence_count": len(found),
        "status": "supported" if found else "unsupported",
    }


def _evidence_row(item: AssessableEvidence) -> dict[str, Any]:
    quality = item.quality
    row: dict[str, Any] = {
        "evidence_id": item.evidence_id,
        "research_need_id": item.research_need_id,
        "source_type": item.source_type,
        "status": item.status,
        "title": item.title,
        "excerpt": review_excerpt(item.excerpt, max_chars=JEV_EXCERPT_CHARS),
        "provider": item.provider,
        "score": item.score,
        "content_hash": item.content_hash,
    }
    if quality is not None:
        row["quality"] = {
            "authority": quality.authority,
            "relevance": quality.relevance,
            "currentness": quality.currentness,
            "source_nature": quality.source_nature,
            "flags": [flag.code for flag in quality.flags],
        }
    return row


def _programmatic_gaps(
    plan: ResearchPlan, evidence: Sequence[AssessableEvidence]
) -> list[str]:
    return [
        need.id
        for need in plan.needs
        if not found_evidence_ids(need.id, evidence)
    ]


def _shrink_to_budget(payload: dict[str, Any], max_state_chars: int) -> dict[str, Any]:
    shrunk = dict(payload)
    evidence = list(shrunk.get("evidence") or [])
    while evidence and len(_encode(shrunk)) > max_state_chars:
        evidence.pop()
        shrunk["evidence"] = evidence
    if len(_encode(shrunk)) > max_state_chars:
        shrunk["objective"] = str(shrunk.get("objective") or "")[:400]
    return shrunk


def _encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def objective_text(
    *,
    objective: ResearchObjective | None,
    plan: ResearchPlan,
) -> str:
    if objective is not None and objective.objective.strip():
        return objective.objective.strip()
    return " ".join(need.question for need in plan.needs)
