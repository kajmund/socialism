"""Graph-side audit counts, cross-checkable against the SQL audit report.

This is the read half of ``audit.py`` migrated to OverGraph: counts by graph label so the
audit can be verified against the SQL mirror while that mirror still exists. Duplicate
cleanup stays with the SQL write path until parcel 5.
"""

from __future__ import annotations

from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import (
    CLAIM,
    CONTRADICTS,
    ENTITY,
    SUPPORTS,
    VERIFICATION_OBSERVATION,
)
from app.services.overgraph.legal_claims import EVIDENCE


def graph_audit_counts(catalog: Catalog) -> dict[str, int]:
    return {
        "claims": catalog.count_nodes_by_labels([CLAIM]),
        "entities": catalog.count_nodes_by_labels([ENTITY]),
        "observations": catalog.count_nodes_by_labels([VERIFICATION_OBSERVATION]),
        "evidence_links": catalog.count_nodes_by_labels([EVIDENCE]),
        "supports_edges": catalog.count_edges_by_label(SUPPORTS),
        "contradicts_edges": catalog.count_edges_by_label(CONTRADICTS),
    }
