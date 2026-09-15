"""Auditable evidence-quality scoring. No retrieval, no domain hierarchy.

Quality distinguishes “evidence exists” from “this item is authoritative,
relevant, current, primary, and independently corroborated enough to inspect”.
Scoring is generic: it only reads declared provider/provenance keys.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from app.services.research.models import ResearchNeed
from app.services.research.provider import KnowledgeProviderDescriptor

EVIDENCE_QUALITY_POLICY_VERSION = "1"

AuthorityLevel = Literal["unknown", "limited", "official"]
RelevanceLevel = Literal["unknown", "low", "medium", "high"]
CurrentnessLevel = Literal["unknown", "known"]
SourceNature = Literal["unknown", "primary", "secondary"]

AUTHORITY_LEVELS: tuple[AuthorityLevel, ...] = ("unknown", "limited", "official")
RELEVANCE_LEVELS: tuple[RelevanceLevel, ...] = ("unknown", "low", "medium", "high")
CURRENTNESS_LEVELS: tuple[CurrentnessLevel, ...] = ("unknown", "known")
SOURCE_NATURES: tuple[SourceNature, ...] = ("unknown", "primary", "secondary")

DECLARED_AUTHORITY_KEYS: frozenset[str] = frozenset(
    {
        "official_publication",
        "not_official_publication",
        "automated_corpus",
        "primary_source",
        "source_nature",
        "authority_warning",
        "authority_level",
    }
)
DECLARED_RECENCY_KEYS: tuple[str, ...] = (
    "published_at",
    "updated_at",
    "document_date",
    "source_date",
    "issued_at",
    "effective_date",
)

FLAG_NOT_OFFICIAL_PUBLICATION = "not_official_publication"
FLAG_AUTOMATED_CORPUS = "automated_corpus"
FLAG_AUTHORITY_WARNING = "authority_warning"
FLAG_RELEVANCE_FAILED = "relevance_assessment_failed"
FLAG_CONTRADICTORY_AUTHORITY = "contradictory_authority_declaration"

HARD_WARNING_FLAGS: frozenset[str] = frozenset(
    {
        FLAG_NOT_OFFICIAL_PUBLICATION,
        FLAG_AUTHORITY_WARNING,
        FLAG_RELEVANCE_FAILED,
        FLAG_CONTRADICTORY_AUTHORITY,
    }
)


class EvidenceQualityError(Exception):
    """Quality scoring or persistence failed. Not a low-quality outcome."""


@dataclass(frozen=True)
class QualityEvidenceInput:
    """Persisted evidence as the quality scorer is allowed to see it."""

    item_id: str
    original_evidence_id: str | None
    research_need_id: str | None
    source_type: str
    status: str
    title: str | None
    excerpt: str | None
    locator: str | None
    source_id: str | None
    source_url: str | None
    provider: str | None
    provenance: dict[str, object]
    retrieved_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", dict(self.provenance))


@dataclass(frozen=True)
class QualityFlag:
    code: str
    detail: str

    def to_json(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class EvidenceRelevanceJudgment:
    """Structured relevance output. Failure must not be mapped to high."""

    relevance: RelevanceLevel
    rationale: str = ""
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if self.relevance not in RELEVANCE_LEVELS:
            raise EvidenceQualityError(f"Unknown relevance level: {self.relevance}")


class EvidenceRelevanceAssessor(Protocol):
    """Injectable structured-output seam. Must not retrieve."""

    async def judge(
        self,
        need: ResearchNeed,
        item: QualityEvidenceInput,
    ) -> EvidenceRelevanceJudgment: ...


@dataclass(frozen=True)
class EvidenceQualityDraft:
    """Immutable quality artifact ready to persist. Does not mutate evidence."""

    evidence_set_item_id: str
    original_evidence_id: str | None
    scoring_policy_version: str
    authority: AuthorityLevel
    relevance: RelevanceLevel
    currentness: CurrentnessLevel
    source_nature: SourceNature
    source_timestamp: datetime | None
    independence_key: str
    independent_source_count: int
    flags: list[QualityFlag] = field(default_factory=list)
    rationale: str = ""
    declared_signals: dict[str, object] = field(default_factory=dict)
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if self.authority not in AUTHORITY_LEVELS:
            raise EvidenceQualityError(f"Unknown authority level: {self.authority}")
        if self.relevance not in RELEVANCE_LEVELS:
            raise EvidenceQualityError(f"Unknown relevance level: {self.relevance}")
        if self.currentness not in CURRENTNESS_LEVELS:
            raise EvidenceQualityError(f"Unknown currentness level: {self.currentness}")
        if self.source_nature not in SOURCE_NATURES:
            raise EvidenceQualityError(f"Unknown source nature: {self.source_nature}")
        object.__setattr__(self, "flags", list(self.flags))
        object.__setattr__(self, "declared_signals", dict(self.declared_signals))


def quality_model_identity_key(
    *,
    model_provider: str | None,
    model_name: str | None,
    model_version: str | None,
) -> str:
    """Stable unique-key token for policy + model identity.

    Programmatic scoring (all identity fields empty) hashes to one key.
    Provider, name, and version are all required to distinguish models.
    """
    payload = "\x1f".join(
        (
            (model_provider or "").strip(),
            (model_name or "").strip(),
            (model_version or "").strip(),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def independence_key(item: QualityEvidenceInput) -> str:
    """Stable underlying-source identity. Copies of one canonical source collide."""
    for raw in (item.source_id, item.source_url):
        canonical = _canonical_source_identity(raw)
        if canonical:
            return canonical
    provider = (item.provider or "").strip().lower()
    locator = (item.locator or "").strip().lower()
    if provider and locator:
        return f"locator:{provider}:{item.source_type}:{locator}"
    digest = (item.content_hash or "").strip().lower()
    if digest:
        return f"content:{digest}"
    return f"item:{item.item_id}"


def match_provider_descriptor(
    item: QualityEvidenceInput,
    descriptors: Sequence[KnowledgeProviderDescriptor],
) -> KnowledgeProviderDescriptor | None:
    """Find the registration that declared this item's provider. No invented match."""
    provider = (item.provider or "").strip()
    if not provider:
        return None
    exact: list[KnowledgeProviderDescriptor] = []
    nature: list[KnowledgeProviderDescriptor] = []
    for descriptor in descriptors:
        if descriptor.provider_id == provider:
            exact.append(descriptor)
            continue
        if descriptor.provider_id == f"{provider}.{item.source_type}":
            nature.append(descriptor)
            continue
        retrieval = descriptor.authority.get("retrieval_provider")
        if retrieval == provider and item.source_type in descriptor.evidence_natures:
            nature.append(descriptor)
    if len(exact) == 1:
        return exact[0]
    if len(nature) == 1:
        return nature[0]
    return None


def declared_authority_signals(
    item: QualityEvidenceInput,
    descriptor: KnowledgeProviderDescriptor | None,
) -> dict[str, object]:
    """Copy only keys the provider actually declared. Do not infer missing ones."""
    declared: dict[str, object] = {}
    if descriptor is not None:
        for key, value in descriptor.authority.items():
            if key in DECLARED_AUTHORITY_KEYS:
                declared[key] = value
    for key in DECLARED_AUTHORITY_KEYS:
        if key in declared:
            continue
        if key in item.provenance:
            declared[key] = item.provenance[key]
    return declared


def hard_quality_warnings(draft: EvidenceQualityDraft) -> list[str]:
    """Obvious limitations a local assessor may surface. Never a discard rule."""
    warnings: list[str] = []
    for flag in draft.flags:
        if flag.code in HARD_WARNING_FLAGS and flag.detail:
            warnings.append(flag.detail)
    return warnings


def _canonical_source_identity(value: str | None) -> str:
    if not value or not str(value).strip():
        return ""
    text = str(value).strip()
    text = text.split("#", 1)[0].rstrip("/")
    if "://" not in text:
        return text.lower()
    parts = urlsplit(text)
    host = parts.hostname.lower() if parts.hostname else ""
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, "")).rstrip("/")


def _truthy(value: object) -> bool:
    return value is True or value == "true" or value == 1


def _declared_source_nature(signals: Mapping[str, object]) -> SourceNature | None:
    raw = signals.get("source_nature")
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in SOURCE_NATURES:
            return token  # type: ignore[return-value]
        if token == "official":
            return "primary"
    return None


def _parse_source_timestamp(provenance: Mapping[str, object]) -> datetime | None:
    for key in DECLARED_RECENCY_KEYS:
        raw = provenance.get(key)
        parsed = _as_datetime(raw)
        if parsed is not None:
            return parsed
    return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _authority_from_signals(
    signals: Mapping[str, object],
) -> tuple[AuthorityLevel, list[QualityFlag]]:
    flags: list[QualityFlag] = []
    official = _truthy(signals.get("official_publication"))
    not_official = _truthy(signals.get("not_official_publication"))
    automated = _truthy(signals.get("automated_corpus"))
    warning = signals.get("authority_warning")
    declared_level = signals.get("authority_level")

    if not_official:
        flags.append(
            QualityFlag(
                code=FLAG_NOT_OFFICIAL_PUBLICATION,
                detail="Provider declared this material is not an official publication.",
            )
        )
    if automated:
        flags.append(
            QualityFlag(
                code=FLAG_AUTOMATED_CORPUS,
                detail="Provider declared this material comes from an automated corpus.",
            )
        )
    if isinstance(warning, str) and warning.strip():
        flags.append(
            QualityFlag(code=FLAG_AUTHORITY_WARNING, detail=warning.strip())
        )
    if official and not_official:
        flags.append(
            QualityFlag(
                code=FLAG_CONTRADICTORY_AUTHORITY,
                detail="Provider declared both official_publication and not_official_publication.",
            )
        )
        return "unknown", flags
    if official:
        return "official", flags
    if isinstance(declared_level, str) and declared_level.strip().lower() == "official":
        return "official", flags
    if not_official or automated:
        return "limited", flags
    if isinstance(declared_level, str) and declared_level.strip().lower() == "limited":
        return "limited", flags
    return "unknown", flags


def _source_nature_from_signals(signals: Mapping[str, object]) -> SourceNature:
    declared = _declared_source_nature(signals)
    if declared is not None:
        return declared
    if _truthy(signals.get("primary_source")):
        return "primary"
    if _truthy(signals.get("official_publication")):
        return "primary"
    if _truthy(signals.get("not_official_publication")) or _truthy(
        signals.get("automated_corpus")
    ):
        return "secondary"
    return "unknown"


def _rationale(
    *,
    authority: AuthorityLevel,
    relevance: RelevanceLevel,
    currentness: CurrentnessLevel,
    source_nature: SourceNature,
    independent_source_count: int,
    flags: Sequence[QualityFlag],
) -> str:
    parts = [
        f"authority={authority}",
        f"relevance={relevance}",
        f"currentness={currentness}",
        f"source_nature={source_nature}",
        f"independent_sources={independent_source_count}",
    ]
    if flags:
        parts.append("flags=" + ",".join(flag.code for flag in flags))
    return "; ".join(parts) + ". Dimensions come from declared metadata only."


def _found_independence_counts(
    items: Sequence[QualityEvidenceInput],
) -> dict[str, int]:
    """Distinct underlying sources per ResearchNeed among found items."""
    keys_by_need: dict[str, set[str]] = {}
    for item in items:
        if item.status != "found":
            continue
        need_id = item.research_need_id or ""
        keys_by_need.setdefault(need_id, set()).add(independence_key(item))
    return {need_id: len(keys) for need_id, keys in keys_by_need.items()}


async def assess_evidence_quality(
    items: Sequence[QualityEvidenceInput],
    *,
    needs: Sequence[ResearchNeed] = (),
    descriptors: Sequence[KnowledgeProviderDescriptor] = (),
    relevance_assessor: EvidenceRelevanceAssessor | None = None,
    scoring_policy_version: str = EVIDENCE_QUALITY_POLICY_VERSION,
) -> list[EvidenceQualityDraft]:
    """Score each item. Model failure stays unknown; it never upgrades quality."""
    needs_by_id = {need.id: need for need in needs}
    independent_counts = _found_independence_counts(items)
    drafts: list[EvidenceQualityDraft] = []
    for item in items:
        descriptor = match_provider_descriptor(item, descriptors)
        signals = declared_authority_signals(item, descriptor)
        authority, flags = _authority_from_signals(signals)
        source_nature = _source_nature_from_signals(signals)
        source_timestamp = _parse_source_timestamp(item.provenance)
        currentness: CurrentnessLevel = "known" if source_timestamp is not None else "unknown"
        key = independence_key(item)
        independent_source_count = (
            independent_counts.get(item.research_need_id or "", 0)
            if item.status == "found"
            else 0
        )
        relevance: RelevanceLevel = "unknown"
        model_provider = None
        model_name = None
        model_version = None
        need = needs_by_id.get(item.research_need_id or "")
        if relevance_assessor is not None and item.status == "found" and need is not None:
            try:
                judgment = await relevance_assessor.judge(need, item)
            except EvidenceQualityError:
                raise
            except Exception as exc:
                raise EvidenceQualityError(
                    f"Relevance assessor failed for item {item.item_id}"
                ) from exc
            relevance = judgment.relevance
            model_provider = judgment.model_provider
            model_name = judgment.model_name
            model_version = judgment.model_version
        drafts.append(
            EvidenceQualityDraft(
                evidence_set_item_id=item.item_id,
                original_evidence_id=item.original_evidence_id,
                scoring_policy_version=scoring_policy_version,
                authority=authority,
                relevance=relevance,
                currentness=currentness,
                source_nature=source_nature,
                source_timestamp=source_timestamp,
                independence_key=key,
                independent_source_count=independent_source_count,
                flags=flags,
                rationale=_rationale(
                    authority=authority,
                    relevance=relevance,
                    currentness=currentness,
                    source_nature=source_nature,
                    independent_source_count=independent_source_count,
                    flags=flags,
                ),
                declared_signals=signals,
                model_provider=model_provider,
                model_name=model_name,
                model_version=model_version,
            )
        )
    return drafts
