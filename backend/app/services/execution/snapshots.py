"""Historical snapshots of ResearchEvidence (copy, not a live pointer)."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.execution.errors import ExecutionError
from app.services.research.models import ResearchEvidence


@dataclass(frozen=True)
class EvidenceItemSnapshot:
    """Normalized fields persisted on ``evidence_set_items``."""

    research_need_id: str | None
    source_type: str
    status: str
    title: str | None
    excerpt: str | None
    locator: str | None
    source_id: str | None
    source_url: str | None
    provider: str | None
    score: float | None
    provenance: dict[str, Any]
    retrieved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", deepcopy(self.provenance))


def require_json_object(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExecutionError(f"{field} must be a JSON object")
    try:
        json.dumps(value)
    except TypeError as exc:
        raise ExecutionError(f"{field} must be JSON-serializable") from exc
    return deepcopy(value)


def snapshot_research_evidence(evidence: ResearchEvidence) -> EvidenceItemSnapshot:
    """Copy ResearchEvidence into a historical item. Does not keep a live link."""
    provenance = require_json_object(dict(evidence.metadata), field="provenance")
    provenance["research_evidence_id"] = evidence.evidence_id
    return EvidenceItemSnapshot(
        research_need_id=evidence.research_need_id,
        source_type=evidence.source_type,
        status=evidence.status,
        title=evidence.title,
        excerpt=evidence.excerpt,
        locator=evidence.locator,
        source_id=evidence.source_id,
        source_url=evidence.source_url,
        provider=evidence.provider,
        score=evidence.score,
        provenance=provenance,
        retrieved_at=evidence.retrieved_at,
    )


def compute_content_hash(
    *,
    title: str | None,
    excerpt: str | None,
    locator: str | None,
    source_id: str | None,
    source_url: str | None,
    provenance: dict[str, Any],
) -> str:
    payload = json.dumps(
        {
            "excerpt": excerpt,
            "locator": locator,
            "provenance": provenance,
            "source_id": source_id,
            "source_url": source_url,
            "title": title,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
