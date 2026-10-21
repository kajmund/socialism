"""Transitional mirror: a legacy SQL claim write also populates the OverGraph claim.

Parcel 4 migrates readers while the SQL write path is still authoritative. Both stores are
written from the same domain claim here, so parity tests can compare them and so the
OverGraph reader has real data before parcel 5 cuts the SQL write.
"""

from __future__ import annotations

import json

from app.services.knowledge.claims import KnowledgeClaim
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.legal_claims import (
    Support,
    evidence_key,
    add_support,
    link_evidence,
    upsert_legal_claim,
)
from app.services.overgraph.text_units import load_domain_text_unit


def attach_claim_supports(claim_id: str, unit_ids: tuple[str, ...]) -> None:
    """Add graph supports for TextUnits attached after the claim was first written."""
    catalog = require_knowledge()
    for unit_id in unit_ids:
        unit = load_domain_text_unit(catalog, unit_id=unit_id)
        if unit is None:
            continue
        existing = catalog.get_by_key("ClaimEvidence", evidence_key(claim_id, unit.document_version_id))
        current = json.loads(str(existing.props.get("text_unit_ids_json") or "[]")) if existing else []
        merged = sorted({*current, unit_id})
        link_evidence(
            catalog, claim_key=claim_id, document_version_id=unit.document_version_id,
            text_unit_ids=tuple(merged),
        )
        add_support(
            catalog, claim_key=claim_id, document_version_id=unit.document_version_id,
            support=Support(
                text_unit_id=unit_id,
                provenance=({"kind": "text_unit", "ref": unit_id},),
                source_ref=unit.document_id,
            ),
        )


def mirror_claim(claim: KnowledgeClaim, *, key: str | None = None) -> str:
    """Write the logical claim and one evidence link per supporting document version.

    Being accepted by the knowledge pipeline is **not** a Jev verification. Supports are
    therefore mirrored without a verdict (``decision`` empty), so they are inventoriable
    candidates: the claim exists in the graph but ``claim_is_verified`` stays false until a
    real verification records ``SUPPORTED`` with its source and verification version.
    """
    catalog = require_knowledge()
    node = upsert_legal_claim(
        catalog, scope=claim.scope, predicate=claim.predicate, value=claim.value, key=key,
    )
    by_version: dict[str, list[str]] = {}
    for unit_id in claim.supporting_text_unit_ids:
        unit = load_domain_text_unit(catalog, unit_id=unit_id)
        if unit is None:
            continue
        by_version.setdefault(unit.document_version_id, []).append(unit_id)
    for version_id, unit_ids in by_version.items():
        # One evidence node per version holds every supporting clause from that version.
        link_evidence(
            catalog, claim_key=node.key, document_version_id=version_id,
            text_unit_ids=tuple(unit_ids),
        )
        for unit_id in unit_ids:
            add_support(
                catalog, claim_key=node.key, document_version_id=version_id,
                support=Support(
                    text_unit_id=unit_id,
                    provenance=({"kind": "text_unit", "ref": unit_id},),
                    decision=None,
                    verification_version=None,
                    source_ref=unit_id,
                ),
            )
    return node.key
