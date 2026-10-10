"""General knowledge reads shared Graph provenance, never private workspace files."""

import json

import pytest
from sqlalchemy import delete, select

from app.database.graph_v2 import GraphFact, GraphFactSource, GraphNode
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Kund, StoredObject, UserAccount
from app.database.workspace_models import VoiceWorkspace
from app.services.knowledge.models import KnowledgeHit, KnowledgeScope
from app.services.research.graph_reuse import GraphQueryEmbedding, lookup_graph_evidence
from app.services.research.models import RESEARCH_SOURCE_TYPES, ResearchContext, ResearchNeed
from app.services.workspace import search
from app.services.workspace.containers import WorkspaceContainer
from app.services.workspace.service import add_source, create_workspace
from app.services.workspace.sources import read_reference
from app.services.workspaces import create_client_workspace
from app.services.graph_v2.types import NodeInput
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.research import (
    ResearchFactWrite,
    drop_scope_index,
    knowledge_catalog,
    persist_research_fact,
)
from tests.conftest import RESEARCH_TEST_DIM, research_test_vector
from tests.test_research_graph_v2_reuse import Embeddings, NOW, seed_fact
from tests.text_unit_fakes import persisted_text_unit
from tests.test_workspace_connections import (
    another_client,
    command,
    single_connection as single_connection,
)

QUERY = "36 § avtalslagen senare lagändringar"


async def _private_fact(session, identity, parent, *, customer_id=1, owner_id="user-one"):
    source = StoredObject(id=identity, workspace_id=parent, customer_id=customer_id, owner_user_id=owner_id,
        module="dd", kind="underlag", bucket="general-scope-test", object_key=identity,
        filename=f"{identity}.txt", content_type="text/plain", size_bytes=80,
        extraction_status="ok", extracted_text=f"{QUERY}. PRIVATE {identity}.", knowledge_status="ready")
    session.add(source)
    await session.flush()
    scope = f"customer:{customer_id}"
    fields = {"scope_key": scope, "scope_type": "customer", "customer_id": customer_id}
    document = CanonicalDocumentRecord(id=f"document-{identity}", **fields,
        source_object_id=identity, source_type="uploaded_file", canonical_uri=f"stored-object:{identity}",
        title=source.filename, extra={"workspace_id": parent})
    session.add(document)
    await session.flush()
    version = DocumentVersionRecord(id=f"version-{identity}", **fields, document_id=document.id,
        mime_type="text/plain", content_hash=f"hash-{identity}", ingested_at=NOW)
    session.add(version)
    await session.flush()
    unit = await persisted_text_unit(session, id=f"unit-{identity}", **fields,
        document_id=document.id, document_version_id=version.id, ordinal=0,
        text=source.extracted_text, locator="line:1", ingested_at=NOW)
    nodes = [GraphNode(id=f"{identity}-{side}", scope_key=scope, customer_id=customer_id,
        node_type="core.concept", identity_key=f"{identity}-{side}", name=side, normalized_name=side)
        for side in ("source", "target")]
    session.add_all([unit, *nodes])
    await session.flush()
    fact = GraphFact(id=f"fact-{identity}", scope_key=scope, customer_id=customer_id,
        identity_key=identity, source_id=nodes[0].id, target_id=nodes[1].id, predicate="test.policy",
        fact_text=unit.text, normalized_text=unit.text.casefold(), status="active",
        embedding=research_test_vector(), embedding_model=Embeddings.model,
        attributes={"workspace_id": parent, "knowledge_module": "dd"})
    session.add(fact)
    await session.flush()
    session.add(GraphFactSource(fact_id=fact.id, source_kind="text_unit", source_ref=unit.id))
    await session.commit()
    owner = customer_scope(customer_id)
    persist_research_fact(
        knowledge_catalog(),
        ResearchFactWrite(
            fact_id=f"fact-{identity}",
            scope=owner,
            source=NodeInput(node_type="core.concept", name="source", scope=owner),
            target=NodeInput(node_type="core.concept", name="target", scope=owner),
            predicate="test.policy",
            fact_text=unit.text,
            unit=TextUnitWrite(
                unit_id=unit.id,
                scope=owner,
                document_id=document.id,
                document_version_id=version.id,
                text=unit.text,
                content_hash=unit.content_hash,
                ordinal=0,
                locator="line:1",
                ingested_at=NOW,
                embedding=tuple(research_test_vector()),
            ),
            embedding=tuple(research_test_vector()),
            attributes={"workspace_id": parent, "knowledge_module": "dd"},
            source_key=f"{identity}-source",
            target_key=f"{identity}-target",
        ),
    )
    return {"text_unit_id": unit.id, "document_version_id": version.id, "document_id": document.id}


@pytest.fixture
async def general_documents(single_connection, research_overgraph):
    factory, old_ids = single_connection
    async with factory() as session:
        user = await session.get(UserAccount, old_ids[0])
        company = (await session.get(VoiceWorkspace, old_ids[1])).workspace_id
        active = await create_client_workspace(session, customer_id=1, user_id=user.id, name="Active")
        sibling = await create_client_workspace(session, customer_id=1, user_id=user.id, name="Sibling")
        canvas = await create_workspace(session, user, title="Client documents", module="dd",
            container=WorkspaceContainer(workspace_id=active.id))
        session.add(Kund(id=2, name="Foreign", slug="general-foreign", available_modules=["dd"]))
        await session.flush()
        foreign_user = UserAccount(id="foreign-owner", email="foreign@general.test", role="user", kund_id=2)
        session.add(foreign_user)
        await session.flush()
        foreign = await create_workspace(session, foreign_user, title="Foreign documents", module="dd")
        await session.commit()
        await seed_fact(session, scope="shared")
        await session.commit()
        indexed = {}
        for identity, parent, customer, owner in [
            ("company-policy", company, 1, user.id),
            ("active-contract", active.id, 1, user.id),
            ("sibling-contract", sibling.id, 1, user.id),
            ("foreign-contract", foreign.workspace_id, 2, foreign_user.id),
        ]:
            indexed[identity] = await _private_fact(session, identity, parent, customer_id=customer, owner_id=owner)
        for identity in ("company-policy", "active-contract"):
            await add_source(session, canvas, identity)
        canvas.state = {**canvas.state, "knowledge_scope": "general"}
        await session.commit()
        ids = user.id, canvas.id
        parents = company, active.id
    return factory, ids, indexed, parents


def _checked_embeddings(factory, monkeypatch):
    class CheckedEmbeddings(Embeddings):
        async def embed(self, texts):
            await another_client(factory)
            return await super().embed(texts)

    monkeypatch.setattr(search.OpenAIEmbeddingProvider, "from_settings", CheckedEmbeddings)


@pytest.mark.parametrize("query", [QUERY, "No lexical match whatsoever"])
async def test_general_excludes_company_and_client_document_graph_facts(general_documents, monkeypatch, query):
    factory, ids, _indexed, _parents = general_documents
    _checked_embeddings(factory, monkeypatch)
    result = await command(factory, ids, name="search_knowledge", args={"query": query})
    assert {item["source_id"] for item in result["items"]} == {"version-shared"}
    assert "PRIVATE" not in json.dumps(result)
    assert result["items"][0]["snapshot"]["scope_type"] == "shared"
    assert result["items"][0]["snapshot"]["customer_id"] is None
    async with factory() as session:
        canvas = await session.get(VoiceWorkspace, ids[1])
        assert not (await read_reference(session, canvas, result["items"][0]["reference_id"]))["stale"]


async def test_general_source_basis_is_the_same_for_different_customers(general_documents, monkeypatch):
    factory, ids, _indexed, _parents = general_documents
    async with factory.begin() as session:
        foreign = await session.scalar(select(VoiceWorkspace).where(VoiceWorkspace.owner_user_id == "foreign-owner"))
        foreign.state = {**foreign.state, "knowledge_scope": "general"}
        foreign_ids = foreign.owner_user_id, foreign.id
    _checked_embeddings(factory, monkeypatch)
    for reader in (ids, foreign_ids):
        result = await command(factory, reader, name="search_knowledge", args={"query": QUERY})
        assert {item["source_id"] for item in result["items"]} == {"version-shared"}
        assert {item["snapshot"]["customer_id"] for item in result["items"]} == {None}
        assert "PRIVATE" not in json.dumps(result)


async def test_general_empty_shared_graph_does_not_embed_private_material(general_documents, monkeypatch):
    factory, ids, _indexed, _parents = general_documents
    async with factory.begin() as session:
        await session.execute(delete(GraphFact).where(GraphFact.scope_key == "shared"))
        drop_scope_index(knowledge_catalog(), "shared")

    def forbidden_embeddings():
        raise AssertionError("An empty shared graph must not embed just because private facts exist")

    monkeypatch.setattr(search.OpenAIEmbeddingProvider, "from_settings", forbidden_embeddings)
    result = await command(factory, ids, name="search_knowledge", args={"query": QUERY})
    assert result["items"] == [] and result["gaps"] == [{"status": "not_found"}]


async def test_research_reuse_keeps_shared_company_and_active_client_visibility(general_documents):
    factory, ids, _indexed, parents = general_documents
    async with factory() as session:
        context = ResearchContext(scope=KnowledgeScope(customer_id=1, module="dd",
            workspace_id=parents[1], readable_workspace_ids=parents))
        evidence = await lookup_graph_evidence(session,
            need=ResearchNeed(id="reuse", question=QUERY, why_needed="", source_types=list(RESEARCH_SOURCE_TYPES)),
            context=context, query_embedding=GraphQueryEmbedding(Embeddings.model, RESEARCH_TEST_DIM, research_test_vector()), limit=10)
    assert {item.metadata["graph_fact_ids"][0] for item in evidence} == {
        "fact-shared", "fact-company-policy", "fact-active-contract"}


async def test_workspace_search_keeps_active_client_and_company_documents(general_documents, monkeypatch):
    factory, ids, indexed, _parents = general_documents
    async with factory.begin() as session:
        canvas = await session.get(VoiceWorkspace, ids[1])
        canvas.state = {**canvas.state, "knowledge_scope": "workspace"}
    _checked_embeddings(factory, monkeypatch)

    class Vectors:
        async def search(self, embedded_query):
            await another_client(factory)
            identity, = embedded_query.query.scope.allowed_source_object_ids
            assert identity in {"company-policy", "active-contract"}
            return [KnowledgeHit(document_id=indexed[identity]["document_id"], provider="supabase",
                title="Untrusted title", excerpt="Untrusted vector excerpt", locator="line:1",
                score=0.9, metadata=indexed[identity])]

    monkeypatch.setattr(search, "require_knowledge_vector_store", Vectors)
    result = await command(factory, ids, name="search_knowledge", args={"query": QUERY})
    assert {item["source_id"] for item in result["items"]} == {"company-policy", "active-contract"}
    assert all("PRIVATE" in item["excerpt"] for item in result["items"])
