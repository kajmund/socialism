"""One evidence-set row per canonical passage.

Knowledge reuse and provider retrieval hash different evidence passage ids for
the same text unit, so the hashed id does not collapse them. Membership uses
``document_version_id`` plus each text-unit id. Different passages and
different sources stay, even when the excerpts agree.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.observability.events import EVENT_DATASET_RESEARCH, log_event
from app.services.research.models import ResearchEvidence, research_evidence

logger = logging.getLogger(__name__)

PATH_KNOWLEDGE_REUSE = "knowledge_reuse"
PATH_CLAIM = "claim"
PATH_PROVIDER_RETRIEVAL = "provider_retrieval"
_DISCOVERY_PATHS = frozenset({PATH_KNOWLEDGE_REUSE, PATH_CLAIM, PATH_PROVIDER_RETRIEVAL})
_UNIT_FIELDS = ("text_unit_ids", "supporting_text_unit_ids")
_REUSE_ORIGIN_PERSISTENT = "persistent_knowledge"


@dataclass(frozen=True)
class CanonicalDedupResult:
    evidence: tuple[ResearchEvidence, ...]
    knowledge_candidates: int
    new_candidates: int
    duplicates_removed: int
    unique_evidence: int
    unique_passages: int


def canonical_passage_keys(metadata: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    """``(document_version_id, passage_id)`` for every text unit on the item."""
    version = _version_id(metadata.get("document_version_id"))
    if version is None:
        return ()
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for field in _UNIT_FIELDS:
        for unit_id in _string_ids(metadata.get(field)):
            key = (version, unit_id)
            if key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return tuple(keys)


def is_knowledge_reuse(metadata: Mapping[str, object], provider: str | None) -> bool:
    if provider == "knowledge_claim":
        return True
    reuse = metadata.get("reuse")
    return isinstance(reuse, dict) and reuse.get("origin") == _REUSE_ORIGIN_PERSISTENT


def discovery_records(
    metadata: Mapping[str, object],
    *,
    research_need_id: str,
    provider: str | None,
) -> list[dict[str, str]]:
    """How this item was found. Existing records win over inference."""
    existing = metadata.get("discovered_via")
    if isinstance(existing, list):
        records: list[dict[str, str]] = []
        for entry in existing:
            if not isinstance(entry, dict):
                continue
            cleaned = _clean_record(entry)
            if cleaned is not None:
                records.append(cleaned)
        if records:
            return records
    provider_name = provider or ""
    if is_knowledge_reuse(metadata, provider):
        records = [
            _path_record(
                PATH_KNOWLEDGE_REUSE,
                research_need_id=research_need_id,
                provider=provider_name,
            )
        ]
        for claim_id in _string_ids(metadata.get("knowledge_claim_ids")):
            records.append(
                {
                    "path": PATH_CLAIM,
                    "claim_id": claim_id,
                    "research_need_id": research_need_id,
                }
            )
        return records
    return [
        _path_record(
            PATH_PROVIDER_RETRIEVAL,
            research_need_id=research_need_id,
            provider=provider_name,
        )
    ]


def merge_discovery(
    existing: object,
    incoming: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    sources: list[object] = []
    if isinstance(existing, list):
        sources.extend(existing)
    sources.extend(incoming)
    for entry in sources:
        if not isinstance(entry, dict):
            continue
        cleaned = _clean_record(entry)
        if cleaned is None:
            continue
        key = (
            cleaned.get("path", ""),
            cleaned.get("claim_id", ""),
            cleaned.get("research_need_id", ""),
            cleaned.get("provider", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        records.append(cleaned)
    return records


def narrow_passage_ids(
    metadata: Mapping[str, object],
    keys: Sequence[tuple[str, str]],
) -> dict[str, object]:
    """Keep only the passage ids in ``keys``. Other provenance stays."""
    allowed = {passage_id for _, passage_id in keys}
    updated = dict(metadata)
    for field in _UNIT_FIELDS:
        raw = updated.get(field)
        if not isinstance(raw, list):
            continue
        updated[field] = [unit_id for unit_id in _string_ids(raw) if unit_id in allowed]
    return updated


def narrow_locator(
    locator: str | None,
    keys: Sequence[tuple[str, str]],
    fresh_keys: Sequence[tuple[str, str]],
) -> str | None:
    """Rewrite a locator that is itself the comma-joined passage id list."""
    if locator is None:
        return None
    tokens = [part.strip() for part in locator.split(",") if part.strip()]
    known = {passage_id for _, passage_id in keys}
    if not tokens or any(token not in known for token in tokens):
        return locator
    return ",".join(passage_id for _, passage_id in fresh_keys)


def union_passage_fields(
    base: Mapping[str, object],
    incoming: Mapping[str, object],
) -> dict[str, object]:
    """Add incoming passage ids when they belong to the same document version."""
    updated = dict(base)
    incoming_version = _version_id(incoming.get("document_version_id"))
    current_version = _version_id(updated.get("document_version_id"))
    if current_version is None and incoming_version is not None:
        updated["document_version_id"] = incoming_version
        current_version = incoming_version
    if incoming_version is not None and current_version != incoming_version:
        return updated
    for field in _UNIT_FIELDS:
        extra = _string_ids(incoming.get(field))
        if not extra:
            continue
        merged = _string_ids(updated.get(field))
        seen = set(merged)
        for unit_id in extra:
            if unit_id in seen:
                continue
            seen.add(unit_id)
            merged.append(unit_id)
        updated[field] = merged
    return updated


def dedupe_canonical_evidence(items: Sequence[ResearchEvidence]) -> CanonicalDedupResult:
    """Collapse copies of the same passage. Keep every discovery path."""
    owners: dict[tuple[str, str], int] = {}
    output: list[ResearchEvidence] = []
    knowledge_candidates = 0
    new_candidates = 0
    duplicates_removed = 0
    for item in items:
        if item.status != "found":
            output.append(item)
            continue
        if is_knowledge_reuse(item.metadata, item.provider):
            knowledge_candidates += 1
        else:
            new_candidates += 1
        keys = canonical_passage_keys(item.metadata)
        if not keys:
            output.append(item)
            continue
        records = discovery_records(
            item.metadata,
            research_need_id=item.research_need_id,
            provider=item.provider,
        )
        fresh = tuple(key for key in keys if key not in owners)
        taken = tuple(key for key in keys if key in owners)
        if taken:
            _attach_discovery(output, owners, taken, records)
        if not fresh:
            duplicates_removed += 1
            continue
        metadata = narrow_passage_ids(item.metadata, fresh)
        metadata["discovered_via"] = records
        stored = replace_evidence_metadata(
            item,
            metadata,
            locator=narrow_locator(item.locator, keys, fresh),
        )
        index = len(output)
        output.append(stored)
        for key in fresh:
            owners[key] = index
    unique_evidence = sum(1 for item in output if item.status == "found")
    return CanonicalDedupResult(
        evidence=tuple(output),
        knowledge_candidates=knowledge_candidates,
        new_candidates=new_candidates,
        duplicates_removed=duplicates_removed,
        unique_evidence=unique_evidence,
        unique_passages=len(owners),
    )


def replace_evidence_metadata(
    item: ResearchEvidence,
    metadata: Mapping[str, object],
    *,
    locator: str | None = None,
) -> ResearchEvidence:
    return research_evidence(
        research_need_id=item.research_need_id,
        source_type=item.source_type,
        status=item.status,
        title=item.title,
        excerpt=item.excerpt,
        locator=item.locator if locator is None else locator,
        source_id=item.source_id,
        source_url=item.source_url,
        provider=item.provider,
        score=item.score,
        retrieved_at=item.retrieved_at,
        metadata=dict(metadata),
        legal_result=item.legal_result,
    )


def log_canonical_dedup(
    *,
    scope: str,
    knowledge_candidates: int,
    new_candidates: int,
    duplicates_removed: int,
    unique_evidence: int,
    unique_passages: int,
) -> None:
    log_event(
        logger,
        "research.evidence.canonical_dedup",
        dataset=EVENT_DATASET_RESEARCH,
        outcome="success",
        fields={
            "research": {
                "scope": scope,
                "knowledge_candidates": knowledge_candidates,
                "new_candidates": new_candidates,
                "duplicates_removed": duplicates_removed,
                "unique_evidence": unique_evidence,
                "unique_passages": unique_passages,
            }
        },
    )


def _attach_discovery(
    output: list[ResearchEvidence],
    owners: dict[tuple[str, str], int],
    taken: Sequence[tuple[str, str]],
    records: Sequence[Mapping[str, object]],
) -> None:
    seen: set[int] = set()
    for key in taken:
        index = owners[key]
        if index in seen:
            continue
        seen.add(index)
        current = output[index]
        metadata = dict(current.metadata)
        metadata["discovered_via"] = merge_discovery(metadata.get("discovered_via"), records)
        output[index] = replace_evidence_metadata(current, metadata)


def _path_record(path: str, *, research_need_id: str, provider: str) -> dict[str, str]:
    record = {"path": path, "research_need_id": research_need_id}
    if provider:
        record["provider"] = provider
    return record


def _clean_record(entry: Mapping[str, object]) -> dict[str, str] | None:
    path = entry.get("path")
    if not isinstance(path, str) or path not in _DISCOVERY_PATHS:
        return None
    record = {"path": path}
    for field in ("research_need_id", "provider", "claim_id"):
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            record[field] = value.strip()
    if path == PATH_CLAIM and "claim_id" not in record:
        return None
    return record


def _version_id(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            ids.append(item.strip())
    return ids
