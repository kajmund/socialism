"""OverGraph-backed document-property persistence (authoritative knowledge graph).

Writes ``Claim`` and ``VerificationObservation`` nodes to OverGraph. This is the
single authoritative store for document properties.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from app.services.document_properties.model import (
    CANDIDATE_KIND,
    VERIFICATION_KIND,
    DocumentProperty,
    DocumentPropertyHit,
    PropertyVerification,
)
from app.services.knowledge.scope import KnowledgeTenantScope, require_persist_scope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.claims import (
    ClaimWrite,
    VerificationObservationWrite,
    find_claims,
    find_claims_by_class,
    find_observations,
    supporting_text_unit_ids,
    upsert_claim,
    upsert_verification_observation,
)
from app.services.overgraph.model import GraphRecord


def _scope(customer_id: int) -> KnowledgeTenantScope:
    return require_persist_scope(customer_id=customer_id)


def _claim_write(prop: DocumentProperty, customer_id: int) -> ClaimWrite:
    return ClaimWrite(
        class_id=prop.class_id,
        document_id=prop.document_id,
        document_version_id=prop.document_version_id,
        value=prop.value,
        polarity=prop.polarity,
        taxonomy_version=prop.taxonomy_version,
        scope=_scope(customer_id),
        source_unit_keys=prop.source_unit_keys,
    )


def _candidate_observation(
    prop: DocumentProperty, customer_id: int,
) -> VerificationObservationWrite:
    return VerificationObservationWrite(
        class_id=prop.class_id,
        document_id=prop.document_id,
        document_version_id=prop.document_version_id,
        value=prop.value,
        polarity=prop.polarity,
        taxonomy_version=prop.taxonomy_version,
        scope=_scope(customer_id),
        kind=CANDIDATE_KIND,
        source_unit_keys=prop.source_unit_keys,
    )


def _verification_observation(
    prop: DocumentProperty, verification: PropertyVerification, customer_id: int,
) -> VerificationObservationWrite:
    return VerificationObservationWrite(
        class_id=prop.class_id,
        document_id=prop.document_id,
        document_version_id=prop.document_version_id,
        value=prop.value,
        polarity=prop.polarity,
        taxonomy_version=prop.taxonomy_version,
        scope=_scope(customer_id),
        kind=VERIFICATION_KIND,
        decision=verification.decision,
        source_unit_keys=verification.source_unit_keys,
        verification_method=verification.verification_method,
        verification_version=verification.verification_version,
        reason_code=verification.reason_code,
    )


async def persist_supported_property(
    catalog: Catalog,
    prop: DocumentProperty,
    verification: PropertyVerification,
    *,
    customer_id: int,
) -> GraphRecord:
    """SUPPORTED -> durable Claim node plus a verification observation."""
    node = await asyncio.to_thread(upsert_claim, catalog, _claim_write(prop, customer_id))
    await asyncio.to_thread(
        upsert_verification_observation,
        catalog,
        _verification_observation(prop, verification, customer_id),
    )
    return node


async def persist_candidate_property(
    catalog: Catalog, prop: DocumentProperty, *, customer_id: int,
) -> GraphRecord:
    """Discovery candidate -> typed observation so unverified docs stay findable."""
    return await asyncio.to_thread(
        upsert_verification_observation, catalog, _candidate_observation(prop, customer_id),
    )


async def persist_property_verification(
    catalog: Catalog,
    prop: DocumentProperty,
    verification: PropertyVerification,
    *,
    customer_id: int,
) -> GraphRecord:
    """Record a Jev decision. UNSUPPORTED never supersedes an existing claim."""
    return await asyncio.to_thread(
        upsert_verification_observation,
        catalog,
        _verification_observation(prop, verification, customer_id),
    )


@dataclass(frozen=True)
class LookupPagination:
    limit: int = 100
    supported_after: int | None = None
    candidate_after: int | None = None


@dataclass(frozen=True)
class PropertyLookupPage:
    items: list[DocumentPropertyHit]
    after: int | None


@dataclass(frozen=True)
class PropertyLookup:
    supported: PropertyLookupPage
    candidates: PropertyLookupPage


async def lookup_document_properties(
    catalog: Catalog,
    *,
    customer_id: int,
    class_id: str,
    value: object | None = None,
    include_candidates: bool = True,
    page: LookupPagination = LookupPagination(),
) -> PropertyLookup:
    """Exact, keyset-paginated lookup over supported claims and unverified candidates."""
    scope = _scope(customer_id)

    def _lookup() -> PropertyLookup:
        if value is None:
            rows, supported_next = find_claims_by_class(
                catalog, scope=scope, class_id=class_id,
                limit=page.limit, after=page.supported_after,
            )
        else:
            rows, supported_next = find_claims(
                catalog, scope=scope, class_id=class_id, value=value,
                limit=page.limit, after=page.supported_after,
            )
        supported = PropertyLookupPage(
            items=[_hit(catalog, row, status="supported") for row in rows],
            after=supported_next,
        )
        candidates = PropertyLookupPage(items=[], after=None)
        if include_candidates:
            cand_rows, cand_next = find_observations(
                catalog, scope=scope, class_id=class_id, kind=CANDIDATE_KIND,
                limit=page.limit, after=page.candidate_after,
            )
            candidates = PropertyLookupPage(
                items=[_hit(catalog, row, status="candidate") for row in cand_rows],
                after=cand_next,
            )
        return PropertyLookup(supported=supported, candidates=candidates)

    return await asyncio.to_thread(_lookup)


def _hit(catalog: Catalog, row: GraphRecord, *, status: str) -> DocumentPropertyHit:
    if status == "supported" and row.engine_id is not None:
        units = supporting_text_unit_ids(catalog, row.engine_id)
    else:
        units = _json_units(row.props.get("source_unit_keys_json"))
    props = row.props
    return DocumentPropertyHit(
        document_id=str(props.get("document_id", "")),
        class_id=str(props.get("class_id", "")),
        value=props.get("value"),
        polarity=str(props.get("polarity", "positive")),
        taxonomy_version=str(props.get("taxonomy_version", "")),
        status=status,
        source_unit_keys=units,
    )


def _json_units(raw: object) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        parsed = json.loads(str(raw))
    except (ValueError, TypeError):
        return ()
    return tuple(str(item) for item in parsed)
