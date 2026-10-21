"""Batch graph writes. Embeddings and Jev run outside any write transaction."""

from collections.abc import Sequence

from app.services.graph_v2.types import Decision, FactInput, FactJudge, NodeInput, TextEmbedder
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.model import GraphRecord, TextUnitWrite
from app.services.overgraph.write import (
    fact_key,
    upsert_entity,
    upsert_exact_fact,
    upsert_text_unit,
    write_fact,
)


async def resolve_fact(
    catalog: Catalog,
    proposed: FactInput,
    *,
    judge: FactJudge | None = None,
    embedder: TextEmbedder | None = None,
) -> tuple[GraphRecord, Decision]:
    """Write the source-anchored fact. Identity is deterministic; no semantic gate.

    ``judge`` and ``embedder`` are accepted for call-site compatibility but never decide
    whether a fact node may be created: a repeated write of the same source occurrence is
    idempotent, everything else is a new fact. Semantic relations are a separate workflow
    over already stored facts.
    """
    exact = upsert_exact_fact(catalog, proposed)
    if exact is not None:
        return exact, "SAME"
    row = write_fact(catalog, proposed)
    return row, "DISTINCT"


async def ingest_document_units(
    catalog: Catalog, units: Sequence[TextUnitWrite], *, ingest_mode: bool = False,
) -> list[GraphRecord]:
    if ingest_mode:
        catalog.ingest_mode()
    try:
        written = [upsert_text_unit(catalog, unit) for unit in units]
    finally:
        if ingest_mode:
            catalog.end_ingest()
    return written


def ingest_entities(catalog: Catalog, nodes: Sequence[NodeInput]) -> list[GraphRecord]:
    return [upsert_entity(catalog, node) for node in nodes]


def fact_identity_key(proposed: FactInput) -> str:
    return fact_key(proposed)
