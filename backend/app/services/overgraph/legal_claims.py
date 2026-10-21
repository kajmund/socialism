"""Logical legal claims with per-document evidence links.

Two different identities must not be mixed:

* the **claim** is logical: ``scope + predicate + canonical value`` — one node no matter how
  many documents support it;
* the **evidence link** is per document version: it carries the document version, the
  supporting TextUnits, the provenance and its own validity window.

Deleting a document therefore removes only its evidence links. The claim stays, and losing
the last evidence link means "no longer verified" — never a negative claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.knowledge.identity import knowledge_claim_identity
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import (
    ANSWERED_BY,
    CLAIM,
    CONTRADICTS,
    LINKED,
    SUPPORTS,
    TEXT_UNIT,
    scope_label,
)
from app.services.overgraph.model import GraphRecord

EVIDENCE = "ClaimEvidence"
HAS_EVIDENCE = "HAS_EVIDENCE"
SUPPORTED_BY = "SUPPORTED_BY"
# Jev verdicts. Only SUPPORTED verifies evidence; a discovery candidate carries no verdict.
VERIFIED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
UNDECIDED = "UNDECIDED"


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _ms(value: datetime | None) -> int:
    return int(value.timestamp() * 1000) if value is not None else 0


def legal_claim_key(scope: KnowledgeTenantScope, predicate: str, value: object) -> str:
    """Stable logical identity: no document or document version enters the key."""
    return knowledge_claim_identity(scope_key=scope.scope_key, predicate=predicate, value=value)


def upsert_legal_claim(
    catalog: Catalog, *, scope: KnowledgeTenantScope, predicate: str, value: object,
    key: str | None = None,
) -> GraphRecord:
    key = key or legal_claim_key(scope, predicate, value)
    existing = catalog.get_by_key(CLAIM, key)
    created_at_ms = 0
    if existing is not None:
        created_at_ms = int(existing.props.get("created_at_ms") or 0)
    if not created_at_ms:
        created_at_ms = _now_ms()
    catalog.upsert_node(
        [CLAIM, scope_label(scope.scope_key)],
        key,
        props={
            "scope_key": scope.scope_key,
            "predicate": predicate,
            "value_json": json.dumps(value, ensure_ascii=False, sort_keys=True),
            "status": "active",
            "created_at_ms": created_at_ms,
        },
    )
    claim = catalog.get_by_key(CLAIM, key)
    if claim is None:
        raise RuntimeError(f"claim {key} was not written")
    return claim


def claim_in_graph(catalog: Catalog, *, scope_key: str, identity: str) -> GraphRecord | None:
    """The logical claim for an identity key, restricted to the requested scope."""
    row = catalog.get_by_key(CLAIM, identity)
    if row is None:
        return None
    if str(row.props.get("scope_key") or "") != scope_key:
        return None
    return row


def evidence_key(claim_key: str, document_version_id: str) -> str:
    return f"{claim_key}#evidence#{document_version_id}"


def link_evidence(
    catalog: Catalog,
    *,
    claim_key: str,
    document_version_id: str,
    text_unit_ids: tuple[str, ...] = (),
    provenance: list[dict[str, str]] | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> GraphRecord:
    """Attach one document version's support. Idempotent per (claim, version)."""
    claim = catalog.get_by_key(CLAIM, claim_key)
    if claim is None or claim.engine_id is None:
        raise RuntimeError(f"cannot link evidence to missing claim {claim_key}")
    existing = catalog.get_by_key(EVIDENCE, evidence_key(claim_key, document_version_id))
    previous: list[str] = []
    if existing is not None:
        previous = json.loads(str(existing.props.get("text_unit_ids_json") or "[]"))
    catalog.upsert_node(
        [EVIDENCE],
        evidence_key(claim_key, document_version_id),
        props={
            "claim_key": claim_key,
            "document_version_id": document_version_id,
            # Supports accumulate: a re-mirror must never silently drop evidence.
            "text_unit_ids_json": json.dumps(sorted(set(previous) | set(text_unit_ids))),
            "provenance_json": json.dumps(provenance or [], ensure_ascii=False, sort_keys=True),
            "status": "active",
            "valid_from_ms": _ms(valid_from),
            "valid_to_ms": _ms(valid_to),
        },
    )
    link = catalog.get_by_key(EVIDENCE, evidence_key(claim_key, document_version_id))
    if link is None or link.engine_id is None:
        raise RuntimeError("evidence link was not written")
    catalog.upsert_edge(claim.engine_id, link.engine_id, HAS_EVIDENCE)
    return link


@dataclass(frozen=True)
class Support:
    """One clause backing a claim, with its own verdict, validity and provenance."""

    text_unit_id: str
    provenance: tuple[dict[str, str], ...] = ()
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    decision: str | None = None
    verification_version: str | None = None
    source_ref: str | None = None


def add_support(
    catalog: Catalog, *, claim_key: str, document_version_id: str, support: Support,
) -> None:
    """One clause supporting the evidence node, with its own validity and provenance.

    Supports are edges, so one expiring clause never invalidates another clause from the
    same document version. ``decision`` carries the Jev verdict; only ``SUPPORTED`` counts
    as verified evidence, so a lexically discovered candidate never verifies a claim.
    """
    link = catalog.get_by_key(EVIDENCE, evidence_key(claim_key, document_version_id))
    unit = catalog.get_by_key(TEXT_UNIT, support.text_unit_id)
    if link is None or link.engine_id is None or unit is None or unit.engine_id is None:
        raise RuntimeError(
            f"cannot support {claim_key} with missing evidence node or "
            f"TextUnit {support.text_unit_id}"
        )
    catalog.upsert_edge(
        link.engine_id,
        unit.engine_id,
        SUPPORTED_BY,
        props={
            "provenance_json": json.dumps(
                list(support.provenance), ensure_ascii=False, sort_keys=True,
            ),
            "decision": support.decision or "",
            "verification_version": support.verification_version or "",
            "source_ref": support.source_ref or "",
        },
        valid_from=_ms(support.valid_from),
        valid_to=_ms(support.valid_to),
    )


def support_is_valid(catalog: Catalog, *, claim_key: str, document_version_id: str,
                     text_unit_id: str, now: datetime, require_verified: bool = True) -> bool:
    link = catalog.get_by_key(EVIDENCE, evidence_key(claim_key, document_version_id))
    unit = catalog.get_by_key(TEXT_UNIT, text_unit_id)
    if link is None or link.engine_id is None or unit is None or unit.engine_id is None:
        return False
    edge = catalog.get_edge_by_triple(link.engine_id, unit.engine_id, SUPPORTED_BY)
    if edge is None:
        return False
    if require_verified and str(edge.props.get("decision") or "") != VERIFIED:
        return False
    moment = _ms(now)
    if edge.valid_from and edge.valid_from > moment:
        return False
    return not edge.valid_to or moment < edge.valid_to


def mark_claim_superseded(
    catalog: Catalog,
    claim_key: str,
    *,
    superseded_at: datetime,
    valid_to: datetime,
    successor_id: str | None,
) -> None:
    """Close the logical claim: status plus validity window, history stays queryable."""
    claim = catalog.get_by_key(CLAIM, claim_key)
    if claim is None or claim.engine_id is None:
        raise RuntimeError(f"cannot supersede missing claim {claim_key}")
    props = dict(claim.props)
    props.update(
        {
            "status": "superseded",
            "superseded_at_ms": _ms(superseded_at),
            "valid_to_ms": _ms(valid_to),
            "successor_key": successor_id or "",
        },
    )
    catalog.upsert_node(list(claim.labels), claim.key, props=props)


def merge_claims(catalog: Catalog, *, winner_key: str, loser_key: str) -> int:
    """Fold a duplicate claim into the winner: evidence, answers and relations move over.

    Mirrors the SQL cleanup rule (earliest claim wins). Returns the number of graph edges
    that were re-pointed or merged so the caller can report what changed.
    """
    if winner_key == loser_key:
        return 0
    winner = catalog.get_by_key(CLAIM, winner_key)
    loser = catalog.get_by_key(CLAIM, loser_key)
    if winner is None or loser is None or winner.engine_id is None or loser.engine_id is None:
        raise RuntimeError(f"cannot merge {loser_key} into {winner_key}: claim is missing")
    moved = _move_evidence(catalog, winner_key=winner_key, loser=loser)
    moved += _move_outgoing_edges(catalog, winner=winner, loser=loser)
    catalog.delete_node(loser.engine_id)
    return moved


def _move_evidence(catalog: Catalog, *, winner_key: str, loser: GraphRecord) -> int:
    moved = 0
    for engine_id in catalog.neighbors(
        loser.engine_id, direction="outgoing", edge_label_filter=[HAS_EVIDENCE],
    ):
        link = catalog.get(engine_id)
        if link is None or link.engine_id is None:
            continue
        version_id = str(link.props.get("document_version_id") or "")
        units = tuple(json.loads(str(link.props.get("text_unit_ids_json") or "[]")))
        if version_id and units:
            link_evidence(
                catalog, claim_key=winner_key, document_version_id=version_id,
                text_unit_ids=units,
            )
            for unit_id in units:
                add_support(
                    catalog, claim_key=winner_key, document_version_id=version_id,
                    support=Support(
                        text_unit_id=str(unit_id),
                        valid_from=_from_ms(link.props.get("valid_from_ms")),
                        valid_to=_from_ms(link.props.get("valid_to_ms")),
                        source_ref=str(link.props.get("document_version_id") or ""),
                    ),
                )
        catalog.delete_node(link.engine_id)
        moved += 1
    return moved


def _move_outgoing_edges(catalog: Catalog, *, winner: GraphRecord, loser: GraphRecord) -> int:
    moved = 0
    for label in (ANSWERED_BY, SUPPORTS, CONTRADICTS, LINKED):
        for engine_id in catalog.neighbors(
            loser.engine_id, direction="outgoing", edge_label_filter=[label],
        ):
            edge = catalog.get_edge_by_triple(loser.engine_id, engine_id, label)
            if edge is None:
                continue
            catalog.upsert_edge(
                winner.engine_id, engine_id, label,
                props=dict(edge.props), weight=edge.weight,
            )
            moved += 1
    return moved


def _from_ms(value: object) -> datetime | None:
    stamp = int(value or 0)
    return datetime.fromtimestamp(stamp / 1000, tz=UTC) if stamp else None


def claim_is_superseded(catalog: Catalog, claim_key: str) -> bool:
    claim = catalog.get_by_key(CLAIM, claim_key)
    return claim is not None and str(claim.props.get("status") or "") == "superseded"


def supporting_text_units(catalog: Catalog, claim_key: str) -> list[str]:
    """TextUnits that support the claim, read from the graph (evidence links + edges)."""
    claim = catalog.get_by_key(CLAIM, claim_key)
    if claim is None or claim.engine_id is None:
        return []
    units: set[str] = set()
    for engine_id in catalog.neighbors(
        claim.engine_id, direction="outgoing", edge_label_filter=[HAS_EVIDENCE],
    ):
        link = catalog.get(engine_id)
        if link is None or link.engine_id is None:
            continue
        for unit_id in json.loads(str(link.props.get("text_unit_ids_json") or "[]")):
            unit = catalog.get_by_key(TEXT_UNIT, str(unit_id))
            if unit is None or unit.engine_id is None:
                continue
            if catalog.get_edge_by_triple(link.engine_id, unit.engine_id, SUPPORTED_BY) is None:
                continue
            units.add(str(unit_id))
    return sorted(units)


def evidence_links(catalog: Catalog, claim_key: str) -> list[GraphRecord]:
    """Evidence links of a claim, newest document version first (deterministic)."""
    claim = catalog.get_by_key(CLAIM, claim_key)
    if claim is None or claim.engine_id is None:
        return []
    rows = [
        row
        for engine_id in catalog.neighbors(
            claim.engine_id, direction="outgoing", edge_label_filter=[HAS_EVIDENCE],
        )
        if (row := catalog.get(engine_id)) is not None
    ]
    return sorted(rows, key=lambda row: str(row.props.get("document_version_id") or ""), reverse=True)


def claim_is_verified(catalog: Catalog, claim_key: str, *, now: datetime) -> bool:
    """Any active evidence link with at least one support still inside its window."""
    moment = _ms(now)
    for link in evidence_links(catalog, claim_key):
        if str(link.props.get("status") or "") != "active":
            continue
        if int(link.props.get("valid_from_ms") or 0) > moment:
            continue
        valid_to = int(link.props.get("valid_to_ms") or 0)
        if valid_to and moment >= valid_to:
            continue
        if link.engine_id is None:
            continue
        for unit_id in json.loads(str(link.props.get("text_unit_ids_json") or "[]")):
            if support_is_valid(
                catalog, claim_key=claim_key,
                document_version_id=str(link.props["document_version_id"]),
                text_unit_id=str(unit_id), now=now,
            ):
                return True
    return False


def evidence_for_version(catalog: Catalog, document_version_id: str) -> list[GraphRecord]:
    """Evidence links contributed by one document version (indexed property lookup)."""
    rows = []
    for engine_id in catalog.find_nodes(EVIDENCE, "document_version_id", document_version_id):
        row = catalog.get(engine_id)
        if row is not None:
            rows.append(row)
    return rows


def unlink_document_versions(catalog: Catalog, document_version_ids: list[str]) -> int:
    """Remove a document's evidence links only. Claims and other documents stay intact."""
    removed = 0
    for version_id in document_version_ids:
        for row in evidence_for_version(catalog, version_id):
            if row.engine_id is None:
                continue
            catalog.delete_node(row.engine_id)
            removed += 1
    return removed


def unlink_document_version(catalog: Catalog, *, claim_key: str, document_version_id: str) -> bool:
    """Drop one document version's support. Returns whether a link was removed."""
    key = evidence_key(claim_key, document_version_id)
    link = catalog.get_by_key(EVIDENCE, key)
    if link is None or link.engine_id is None:
        return False
    catalog.delete_node(link.engine_id)
    return True
