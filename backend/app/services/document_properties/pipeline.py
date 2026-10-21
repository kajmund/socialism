"""End-to-end document-property verification pipeline.

Discovery -> Jev verification -> persistence. TextUnits are read from the
OverGraph knowledge graph (authoritative) and claims/observations are written
back there; the external Jev call happens with no database connection held.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.jev.system import JevSystemOne
from app.services.document_properties.discovery import extract_document_properties
from app.services.document_properties.graph_persistence import (
    persist_candidate_property,
    persist_property_verification,
    persist_supported_property,
)
from app.services.document_properties.local_dense import top_k_dense
from app.services.document_properties.model import (
    SUPPORTED,
    DocumentProperty,
    MaterializedUnit,
    PropertyVerification,
)
from app.services.document_properties.taxonomy import TAXONOMY
from app.services.document_properties.verification import (
    VerificationOutcome,
    verify_document_property,
)
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.vector_store import TextUnitEmbeddingReader
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.text_units import load_text_units

VERIFICATION_METHOD = "jev"
VERIFICATION_VERSION = "v1"


@dataclass(frozen=True)
class PipelineResult:
    verified: int
    candidates: int
    supported: int
    recovered: int


@dataclass(frozen=True)
class LocalDenseConfig:
    question: str
    embeddings: EmbeddingProvider
    stored: TextUnitEmbeddingReader
    k: int = 5


async def load_document_units(
    catalog: Catalog,
    *,
    document_version_id: str,
) -> list[MaterializedUnit]:
    def _load() -> list[MaterializedUnit]:
        return [
            MaterializedUnit(
                id=row.key,
                text=str(row.props.get("text") or ""),
                document_id=str(row.props.get("document_id") or ""),
                document_version_id=str(row.props.get("document_version_id") or ""),
                section_title=str(row.props.get("section_title") or ""),
            )
            for row in load_text_units(catalog, document_version_id=document_version_id)
        ]

    return await asyncio.to_thread(_load)


async def discover_and_verify(
    catalog: Catalog,
    *,
    customer_id: int,
    document_version_id: str,
    jev: JevSystemOne,
    model: str,
    timeout_seconds: float,
    local_dense: LocalDenseConfig | None = None,
) -> PipelineResult:
    units = await load_document_units(catalog, document_version_id=document_version_id)
    by_key = {unit.id: unit for unit in units}
    candidates = extract_document_properties(units)

    outcomes: list[tuple[DocumentProperty, VerificationOutcome]] = []
    recovered = 0
    for candidate in candidates:
        evidence = [by_key[key] for key in candidate.source_unit_keys if key in by_key]
        if not evidence:
            continue
        outcome = await verify_document_property(
            jev,
            prop=candidate,
            spec=TAXONOMY[candidate.class_id],
            candidate_units=evidence,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        if outcome.decision != SUPPORTED and local_dense is not None:
            extra_ids = await top_k_dense(
                question=local_dense.question,
                units=units,
                embeddings=local_dense.embeddings,
                stored=local_dense.stored,
                exclude=set(candidate.source_unit_keys),
                k=local_dense.k,
            )
            extra_units = [by_key[unit_id] for unit_id in extra_ids if unit_id in by_key]
            second = await verify_document_property(
                jev,
                prop=candidate,
                spec=TAXONOMY[candidate.class_id],
                candidate_units=evidence + extra_units,
                model=model,
                timeout_seconds=timeout_seconds,
            )
            if second.decision == SUPPORTED:
                recovered += 1
            outcome = second
        outcomes.append((candidate, outcome))

    supported = 0
    for candidate, outcome in outcomes:
        verification = _verification(outcome)
        if outcome.decision == SUPPORTED:
            await persist_supported_property(
                catalog, candidate, verification, customer_id=customer_id,
            )
            supported += 1
        else:
            await persist_candidate_property(catalog, candidate, customer_id=customer_id)
            await persist_property_verification(
                catalog, candidate, verification, customer_id=customer_id,
            )
    return PipelineResult(
        verified=len(outcomes),
        candidates=len(candidates),
        supported=supported,
        recovered=recovered,
    )


def _verification(outcome: VerificationOutcome) -> PropertyVerification:
    source_keys = (outcome.source_unit_key,) if outcome.source_unit_key else ()
    return PropertyVerification(
        decision=outcome.decision,
        source_unit_keys=source_keys,
        verification_method=VERIFICATION_METHOD,
        verification_version=VERIFICATION_VERSION,
        supporting_excerpt=outcome.supporting_excerpt,
    )
