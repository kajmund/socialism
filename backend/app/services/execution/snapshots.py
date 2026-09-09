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
    original_evidence_id: str | None = None
    ordinal: int | None = None
    content_hash: str | None = None

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


def snapshot_research_evidence(
    evidence: ResearchEvidence,
    *,
    ordinal: int | None = None,
) -> EvidenceItemSnapshot:
    """Copy ResearchEvidence into a historical item. Does not keep a live link."""
    provenance = require_json_object(dict(evidence.metadata), field="provenance")
    provenance["research_evidence_id"] = evidence.evidence_id
    explicit = provenance.get("content_hash")
    explicit_hash = explicit if isinstance(explicit, str) and explicit.strip() else None
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
        original_evidence_id=evidence.evidence_id,
        ordinal=ordinal,
        content_hash=compute_content_hash(
            excerpt=evidence.excerpt,
            provenance=provenance,
            explicit=explicit_hash,
        ),
    )


def compute_content_hash(
    *,
    excerpt: str | None,
    title: str | None = None,
    locator: str | None = None,
    source_id: str | None = None,
    source_url: str | None = None,
    provenance: dict[str, Any] | None = None,
    explicit: str | None = None,
) -> str:
    """SHA-256 of the content actually seen (excerpt), or an explicit seen hash."""
    del title, locator, source_id, source_url
    if explicit:
        return explicit
    if provenance:
        seen = provenance.get("content_hash")
        if isinstance(seen, str) and seen.strip():
            return seen
    return hashlib.sha256((excerpt or "").encode("utf-8")).hexdigest()
