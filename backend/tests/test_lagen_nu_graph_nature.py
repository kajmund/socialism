"""Graph hydration consumes the real lagen.nu ingest contract, not provider IDs."""

from dataclasses import replace

import pytest

from app.database.models import CanonicalDocumentRecord
from app.services.lagen_nu.canonical_ingest import ingest_lagen_nu_document
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.research.graph_grounding import GraphResearchError
from tests.test_research_graph_v2_reuse import lookup_graph_evidence
from tests.knowledge_fakes import FakeEmbeddingProvider
from tests.test_lagen_nu_canonical_ingest import _document
from tests.conftest import research_test_vector
from tests.test_research_graph_v2_reuse import NOW, context, need, seed_fact
from tests.test_research_graph_v2_reuse import graph_db as graph_db


@pytest.mark.parametrize(
    "uri,source,nature",
    [
        ("https://lagen.nu/1915:218", "sfs", "swedish_law"),
        ("https://lagen.nu/dom/nja/2021s943", "dv", "swedish_case_law"),
        ("https://lagen.nu/prop/1975/76:81", "forarbete", "swedish_preparatory_works"),
    ],
)
async def test_ingested_nature_is_usable_graph_evidence(graph_db, uri, source, nature):
    from app.services.knowledge.persistence import current_text_units
    from app.services.knowledge.scope import customer_scope
    from app.services.overgraph.model import TextUnitWrite
    from app.services.overgraph.research import knowledge_catalog, set_text_unit_refs
    from app.services.overgraph.write import upsert_text_unit

    fact = await seed_fact(graph_db)
    document = replace(_document(uri=uri), source=source)
    result = await ingest_lagen_nu_document(
        graph_db,
        customer_id=1,
        document=document,
        embeddings=FakeEmbeddingProvider(),
        vector_store=MemoryKnowledgeVectorStore(),
    )
    units = await current_text_units(graph_db, result.document_id)
    unit = units[0]
    catalog = knowledge_catalog()
    upsert_text_unit(catalog, TextUnitWrite(
        unit_id=unit.id,
        scope=customer_scope(1),
        document_id=unit.document_id,
        document_version_id=unit.document_version_id,
        text=unit.text,
        content_hash=unit.content_hash,
        ordinal=unit.ordinal,
        locator=unit.locator,
        embedding=tuple(research_test_vector()),
    ))
    set_text_unit_refs(catalog, fact.id, [unit.id])
    hits = await lookup_graph_evidence(
        graph_db,
        need=replace(need(), source_types=[nature]),
        context=context(),
        now=NOW,
    )
    assert len(hits) == 1
    assert hits[0].provider == "graph_v2"
    assert hits[0].source_type == nature
    assert hits[0].source_url == uri
    assert hits[0].metadata["graph_fact_ids"] == [fact.id]
    assert "knowledge_claim_ids" not in hits[0].metadata
    wrong_need = replace(need(), source_types=["case_knowledge"])
    assert await lookup_graph_evidence(graph_db, need=wrong_need, context=context(), now=NOW) == []


async def test_missing_nature_fails_loudly_instead_of_reporting_zero_evidence(graph_db):
    await seed_fact(graph_db)
    document = await graph_db.get(CanonicalDocumentRecord, "doc-customer-1")
    document.source_type = "lagen_nu"
    await graph_db.flush()
    with pytest.raises(GraphResearchError, match="evidence nature migration"):
        await lookup_graph_evidence(graph_db, need=need(), context=context())
