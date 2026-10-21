"""Authoritative claim and verification-observation nodes in OverGraph.

A document property that Jev marks ``SUPPORTED`` becomes a ``Claim`` node (with
``SUPPORTS`` edges from its TextUnits). ``UNSUPPORTED`` / ``UNDECIDED`` (and the
deterministic discovery candidate itself) become ``VerificationObservation`` nodes —
never a claim, and never supersession of an existing claim.

Identity mirrors ``app.services.knowledge.identity`` so an OverGraph claim key is
byte-identical to the SQL ``knowledge_claims.id`` it replaces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.knowledge.identity import (
    canonical_json,
    knowledge_claim_identity,
    knowledge_observation_id,
    normalize_assertion_text,
)
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import (
    DOCUMENT_PROPERTY,
    DOCUMENT_VERSION,
    HAS_CLAIM,
    SUPPORTS,
    TEXT_UNIT,
    VERIFICATION_OBSERVATION,
    scope_label,
)
from app.services.overgraph.model import GraphRecord

OBSERVATION_CLASS = "research_observation"
CANDIDATE_KIND = "document_property_candidate"
VERIFICATION_KIND = "document_property_verification"


@dataclass(frozen=True)
class ClaimWrite:
    """A verified document property to persist as a Claim node."""

    class_id: str
    document_id: str
    document_version_id: str
    value: object
    polarity: str
    taxonomy_version: str
    scope: KnowledgeTenantScope
    source_unit_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationObservationWrite:
    """A discovery candidate or a Jev verification decision (not a claim)."""

    class_id: str
    document_id: str
    document_version_id: str
    value: object
    polarity: str
    taxonomy_version: str
    scope: KnowledgeTenantScope
    kind: str
    decision: str | None = None
    source_unit_keys: tuple[str, ...] = ()
    verification_method: str | None = None
    verification_version: str | None = None
    reason_code: str | None = None


def claim_value(
    *,
    document_id: str,
    document_version_id: str,
    value: object,
    polarity: str,
    taxonomy_version: str,
) -> dict[str, object]:
    # Only the assertion enters claim identity; verification fields must not.
    # document_version_id is part of identity so a new version never inherits a
    # prior version's verified property (spec §5.3). This diverges from the SQL
    # `document_properties._claim_value`, which is document-scoped; cutover rekeys.
    return {
        "document_id": document_id,
        "document_version_id": document_version_id,
        "value": value,
        "polarity": polarity,
        "taxonomy_version": taxonomy_version,
    }


def claim_key(
    scope: KnowledgeTenantScope,
    class_id: str,
    value: dict[str, object],
) -> str:
    return knowledge_claim_identity(
        scope_key=scope.scope_key, predicate=class_id, value=value,
    )


def observation_key(
    scope: KnowledgeTenantScope,
    *,
    kind: str,
    document_version_id: str,
    class_id: str,
    statement_normalized: str,
) -> str:
    return knowledge_observation_id(
        scope_key=scope.scope_key,
        observation_class=OBSERVATION_CLASS,
        kind=kind,
        document_version_id=document_version_id,
        question_key=class_id,
        statement_normalized=statement_normalized,
    )


def _labels(scope: KnowledgeTenantScope) -> list[str]:
    return [scope_label(scope.scope_key)]


def upsert_claim(catalog: Catalog, claim: ClaimWrite) -> GraphRecord:
    value = claim_value(
        document_id=claim.document_id,
        document_version_id=claim.document_version_id,
        value=claim.value,
        polarity=claim.polarity,
        taxonomy_version=claim.taxonomy_version,
    )
    key = claim_key(claim.scope, claim.class_id, value)
    catalog.upsert_node(
        [DOCUMENT_PROPERTY, *_labels(claim.scope)],
        key,
        props={
            "scope_key": claim.scope.scope_key,
            "class_id": claim.class_id,
            "value": claim.value,
            "polarity": claim.polarity,
            "taxonomy_version": claim.taxonomy_version,
            "document_id": claim.document_id,
            "document_version_id": claim.document_version_id,
            "value_json": canonical_json(value),
        },
    )
    node = _require(catalog, DOCUMENT_PROPERTY, key)
    _link_version(catalog, claim, node)
    for unit_id in claim.source_unit_keys:
        unit = catalog.get_by_key(TEXT_UNIT, unit_id)
        if unit is not None and unit.engine_id is not None and node.engine_id is not None:
            catalog.upsert_edge(unit.engine_id, node.engine_id, SUPPORTS)
    return node


def upsert_verification_observation(
    catalog: Catalog, obs: VerificationObservationWrite, *, key: str | None = None,
) -> GraphRecord:
    statement = _statement(obs)
    key = key or observation_key(
        obs.scope,
        kind=obs.kind,
        document_version_id=obs.document_version_id,
        class_id=obs.class_id,
        statement_normalized=statement,
    )
    props: dict[str, object] = {
        "scope_key": obs.scope.scope_key,
        "observation_class": OBSERVATION_CLASS,
        "kind": obs.kind,
        "class_id": obs.class_id,
        "value": obs.value,
        "polarity": obs.polarity,
        "taxonomy_version": obs.taxonomy_version,
        "document_id": obs.document_id,
        "document_version_id": obs.document_version_id,
        "statement": statement,
        "source_unit_keys_json": json.dumps(
            list(obs.source_unit_keys), ensure_ascii=False, sort_keys=True,
        ),
    }
    if obs.decision is not None:
        props["decision"] = obs.decision
    if obs.verification_method is not None:
        props["verification_method"] = obs.verification_method
    if obs.verification_version is not None:
        props["verification_version"] = obs.verification_version
    if obs.reason_code is not None:
        props["reason_code"] = obs.reason_code
    catalog.upsert_node([VERIFICATION_OBSERVATION, *_labels(obs.scope)], key, props=props)
    return _require(catalog, VERIFICATION_OBSERVATION, key)


def declare_claim_indexes(catalog: Catalog) -> list[str]:
    """Declare exact indexes that back D1 property lookups. Returns their states."""
    return [
        catalog.ensure_node_property_index(
            DOCUMENT_PROPERTY,
            {"fields": [{"source": "property", "key": "class_id"}], "kind": "equality"},
        ),
        catalog.ensure_node_property_index(
            DOCUMENT_PROPERTY,
            {
                "fields": [
                    {"source": "property", "key": "class_id"},
                    {"source": "property", "key": "value"},
                ],
                "kind": "equality",
            },
        ),
    ]


def find_claims(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    class_id: str,
    value: object,
    limit: int = 100,
    after: int | None = None,
) -> tuple[list[GraphRecord], int | None]:
    """Exact, scope-isolated, keyset-paginated claim lookup (class_id AND value)."""
    return catalog.query_nodes(
        label_filter={"labels": [DOCUMENT_PROPERTY, scope_label(scope.scope_key)], "mode": "all"},
        filter_spec={
            "and": [
                {"property": "class_id", "eq": class_id},
                {"property": "value", "eq": value},
            ],
        },
        limit=limit,
        after=after,
    )


def find_claims_by_class(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    class_id: str,
    limit: int = 100,
    after: int | None = None,
) -> tuple[list[GraphRecord], int | None]:
    """Exact, scope-isolated, keyset-paginated claim lookup by class_id only."""
    return catalog.query_nodes(
        label_filter={"labels": [DOCUMENT_PROPERTY, scope_label(scope.scope_key)], "mode": "all"},
        filter_spec={"property": "class_id", "eq": class_id},
        limit=limit,
        after=after,
    )


def find_observations(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    class_id: str,
    kind: str,
    limit: int = 100,
    after: int | None = None,
) -> tuple[list[GraphRecord], int | None]:
    """Scope-isolated, keyset-paginated lookup of verification observations."""
    return catalog.query_nodes(
        label_filter={
            "labels": [VERIFICATION_OBSERVATION, scope_label(scope.scope_key)],
            "mode": "all",
        },
        filter_spec={
            "and": [
                {"property": "class_id", "eq": class_id},
                {"property": "kind", "eq": kind},
            ],
        },
        limit=limit,
        after=after,
    )


def supporting_text_unit_ids(catalog: Catalog, claim_engine_id: int) -> tuple[str, ...]:
    """TextUnit keys that SUPPORTS the given claim node."""
    unit_ids = catalog.neighbors(
        claim_engine_id, direction="incoming", edge_label_filter=[SUPPORTS],
    )
    return tuple(
        str(node.key) for node in catalog.get_nodes(unit_ids) if node is not None
    )


def _require(catalog: Catalog, label: str, key: str) -> GraphRecord:
    row = catalog.get_by_key(label, key)
    if row is None:
        raise RuntimeError(f"missing graph node {label}:{key}")
    return row


def _link_version(catalog: Catalog, claim: ClaimWrite, node: GraphRecord) -> None:
    if node.engine_id is None:
        return
    version = catalog.get_by_key(DOCUMENT_VERSION, claim.document_version_id)
    if version is None:
        catalog.upsert_node(
            [DOCUMENT_VERSION, *_labels(claim.scope)],
            claim.document_version_id,
            props={
                "scope_key": claim.scope.scope_key,
                "document_id": claim.document_id,
                "document_version_id": claim.document_version_id,
            },
        )
        version = catalog.get_by_key(DOCUMENT_VERSION, claim.document_version_id)
    if version is not None and version.engine_id is not None:
        catalog.upsert_edge(version.engine_id, node.engine_id, HAS_CLAIM)


def observation_identity(obs: VerificationObservationWrite) -> str:
    """Deterministic node key of an observation write (reuse detection without SQL)."""
    return observation_key(
        obs.scope,
        kind=obs.kind,
        document_version_id=obs.document_version_id,
        class_id=obs.class_id,
        statement_normalized=_statement(obs),
    )


def _statement(obs: VerificationObservationWrite) -> str:
    base = f"{obs.class_id} {obs.value}"
    if obs.decision is not None:
        version = obs.verification_version or ""
        return normalize_assertion_text(f"{base} {obs.decision} {version}")
    return normalize_assertion_text(base)
