"""Domain types for document properties."""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
UNDECIDED = "UNDECIDED"

VERIFICATION_DECISIONS = frozenset({SUPPORTED, UNSUPPORTED, UNDECIDED})

POLARITY_POSITIVE = "positive"
POLARITY_NEGATIVE = "negative"
POLARITY_UNCLEAR = "unclear"

EXTRACTION_DETERMINISTIC = "deterministic_discovery"

# Observation kinds stored in knowledge_observations (research_observation class).
OBSERVATION_CLASS = "research_observation"
CANDIDATE_KIND = "document_property_candidate"
VERIFICATION_KIND = "document_property_verification"


@dataclass(frozen=True)
class DocumentProperty:
    """A proposed typed property of a specific document version."""

    class_id: str
    document_id: str
    document_version_id: str
    value: object
    polarity: str
    taxonomy_version: str
    source_unit_keys: tuple[str, ...]
    extraction_origin: str = EXTRACTION_DETERMINISTIC

    @property
    def assertion_text(self) -> str:
        return f"{self.class_id} {self.value}"


@dataclass(frozen=True)
class PropertyVerification:
    """A Jev verification decision for a document property."""

    decision: str
    source_unit_keys: tuple[str, ...]
    verification_method: str
    verification_version: str
    supporting_excerpt: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class MaterializedUnit:
    """A TextUnit materialized with the fields needed for discovery/verification."""

    id: str
    text: str
    document_id: str
    document_version_id: str
    section_title: str


@dataclass(frozen=True)
class DocumentPropertyHit:
    """A lookup row for one document property."""

    document_id: str
    class_id: str
    value: object
    polarity: str
    taxonomy_version: str
    status: str  # supported | candidate
    source_unit_keys: tuple[str, ...]
