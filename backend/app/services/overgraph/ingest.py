"""Batch graph writes. Embeddings and Jev run outside any write transaction."""

from collections.abc import Sequence
from dataclasses import replace

from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.types import Decision, FactInput, FactJudge, NodeInput, TextEmbedder
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.model import GraphRecord, TextUnitWrite
from app.services.overgraph.write import (
    attach_sources,
    fact_key,
    same_endpoint_facts,
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
    exact = upsert_exact_fact(catalog, proposed)
    if exact is not None:
        return exact, "SAME"
    candidates = same_endpoint_facts(catalog, proposed)
    vector = list(proposed.embedding) if proposed.embedding is not None else None
    if vector is None and embedder is not None:
        vector = (await embedder.embed([proposed.fact_text]))[0]
    if candidates and judge is None:
        raise PermanentGraphError("fact judge required for non-exact candidates")
    contradiction: GraphRecord | None = None
    filled = proposed if vector is None else replace(proposed, embedding=tuple(vector))
    for candidate in candidates[:5]:
        decision = await judge.compare(filled, str(candidate.props.get("fact_text") or ""))
        if decision == "SAME":
            attach_sources(catalog, candidate, proposed.sources)
            return candidate, decision
        if decision == "CONTRADICTS":
            contradiction = contradiction or candidate
            continue
        if decision != "DISTINCT":
            raise PermanentGraphError(f"invalid fact judge decision: {decision}")
    row = write_fact(
        catalog, filled,
        contradiction_key=contradiction.key if contradiction is not None else None,
    )
    return row, "CONTRADICTS" if contradiction is not None else "DISTINCT"


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
