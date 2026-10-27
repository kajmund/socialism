"""Scripted holdout metrics. Never present these as live model quality."""

from __future__ import annotations

from collections.abc import Mapping

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.clause_ssr.match import match_query
from app.services.clause_ssr.types import EmbeddingSpec


def score_holdout(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    embedding: EmbeddingSpec,
    expected: Mapping[str, str | None],
) -> dict[str, float | int]:
    hits = 0
    abstentions = 0
    false_positives = 0
    for unit_id, label in expected.items():
        result = match_query(
            catalog,
            scope=scope,
            embedding=embedding,
            text_unit_id=unit_id,
            k=3,
        )
        if result.abstained:
            abstentions += 1
            if label is None:
                hits += 1
            continue
        predicted = result.labels[0] if result.labels else None
        if predicted == label:
            hits += 1
        else:
            false_positives += 1
    return {
        "precision_at_1": hits / len(expected) if expected else 0.0,
        "abstentions": abstentions,
        "false_positives": false_positives,
    }
