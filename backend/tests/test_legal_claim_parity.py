"""Parity: the real SQL claim write path also feeds the OverGraph legal claim reader."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    KnowledgeClaimRecord,
    Kund,
)
from app.services.knowledge.claims import KnowledgeClaim, knowledge_claim_id
from app.services.knowledge.persist import persist_extracted_knowledge
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.legal_claims import (
    claim_is_verified,
    evidence_links,
    legal_claim_key,
)
from tests.text_unit_fakes import persisted_text_unit

VALUE = {"value": False}
PREDICATE = "outcome.granted"


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Kund(id=1, name="acme", slug="acme", available_modules=["dd"]))
        await db.flush()
        yield db
    await engine.dispose()


async def _document(session: AsyncSession, suffix: str) -> str:
    session.add(CanonicalDocumentRecord(
        id=f"doc-{suffix}", customer_id=1, source_type="upload",
        canonical_uri=f"doc://{suffix}", title=suffix, extra={},
    ))
    version_id = f"ver-{suffix}"
    session.add(DocumentVersionRecord(
        id=version_id, document_id=f"doc-{suffix}", customer_id=1,
        content_hash=f"hash-{suffix}", mime_type="text/plain", extra={},
    ))
    await session.flush()
    await persisted_text_unit(
        session, id=f"tu-{suffix}", document_version_id=version_id,
        document_id=f"doc-{suffix}", customer_id=1, section_id=None, ordinal=0,
        text=f"The court held that the clause was not adjusted ({suffix}).",
    )
    return f"tu-{suffix}"


def _claim(unit_id: str) -> KnowledgeClaim:
    return KnowledgeClaim(
        id=knowledge_claim_id(scope_key="customer:1", predicate=PREDICATE, value=VALUE),
        customer_id=1,
        predicate=PREDICATE,
        value=VALUE,
        supporting_text_unit_ids=(unit_id,),
    )


async def test_real_write_path_populates_the_overgraph_reader_with_the_same_identity(session):
    unit_id = await _document(session, "a")
    claim = _claim(unit_id)
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()

    assert await session.get(KnowledgeClaimRecord, claim.id) is None, (
        "the SQL claim row is no longer written"
    )
    catalog = require_knowledge()
    scope = claim.scope
    key = legal_claim_key(scope, claim.predicate, claim.value)
    assert key == claim.id, "the graph key is the stable claim identity"
    assert catalog.get_by_key("Claim", key) is not None
    links = evidence_links(catalog, key)
    assert [str(link.props["document_version_id"]) for link in links] == ["ver-a"]
    # Acceptance by the knowledge pipeline is not a Jev verification.
    assert claim_is_verified(catalog, key, now=_now()) is False


async def test_two_documents_supporting_the_same_claim_share_one_overgraph_node(session):
    first = await _document(session, "a")
    second = await _document(session, "b")
    await persist_extracted_knowledge(session, claims=[_claim(first)])
    await persist_extracted_knowledge(session, claims=[_claim(second)])
    await session.flush()

    catalog = require_knowledge()
    key = _claim(first).id
    assert catalog.get_by_key("Claim", key) is not None
    links = evidence_links(catalog, key)
    assert sorted(str(link.props["document_version_id"]) for link in links) == ["ver-a", "ver-b"]


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


async def test_an_accepted_claim_without_verified_evidence_exists_but_is_not_verified(session):
    """Mirroring must never promote accepted evidence into legally verified knowledge."""
    unit_id = await _document(session, "c")
    claim = _claim(unit_id)
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()

    catalog = require_knowledge()
    key = legal_claim_key(claim.scope, claim.predicate, claim.value)
    assert catalog.get_by_key("Claim", key) is not None, "the claim must be in the graph"
    links = evidence_links(catalog, key)
    assert links, "the evidence link must be inventoriable"
    assert claim_is_verified(catalog, key, now=_now()) is False, (
        "an accepted claim without a Jev SUPPORTED verdict must not be verified"
    )


async def test_an_explicit_verification_verifies_the_mirrored_claim(session):
    """Only a recorded verdict with source and verification version verifies evidence."""
    from app.services.overgraph.legal_claims import VERIFIED, Support, add_support

    unit_id = await _document(session, "d")
    claim = _claim(unit_id)
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()

    catalog = require_knowledge()
    key = legal_claim_key(claim.scope, claim.predicate, claim.value)
    assert claim_is_verified(catalog, key, now=_now()) is False
    add_support(
        catalog, claim_key=key, document_version_id="ver-d",
        support=Support(
            text_unit_id=unit_id,
            decision=VERIFIED,
            verification_version="jev-2026-10",
            source_ref="lagnu://nja/2005s142",
        ),
    )
    assert claim_is_verified(catalog, key, now=_now()) is True


async def test_graph_reader_matches_the_sql_claim_lookup(session):
    """Reading by (scope_key, identity) finds the same claim in both stores."""
    from app.services.overgraph.legal_claims import claim_in_graph

    unit_id = await _document(session, "e")
    claim = _claim(unit_id)
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()

    graph = claim_in_graph(require_knowledge(), scope_key="customer:1", identity=claim.id)
    assert graph is not None
    assert graph.key == claim.id
    assert graph.props["predicate"] == claim.predicate
    assert graph.props["scope_key"] == "customer:1"
    assert claim_in_graph(require_knowledge(), scope_key="customer:2", identity=claim.id) is None


async def test_entity_mirror_keeps_the_sql_identity_and_namespaced_type(session):
    """The real write path mirrors entities under their SQL id, with a valid graph label."""
    from app.database.models import KnowledgeEntityRecord
    from app.services.knowledge.entities import knowledge_entity

    entity = knowledge_entity(
        customer_id=1, entity_type="legal.source",
        key="https://lagen.nu/1915:218", name="Avtalslagen", extra={"kind": "statute"},
    )
    await persist_extracted_knowledge(session, entities=[entity])
    await session.flush()

    assert await session.get(KnowledgeEntityRecord, entity.id) is None, (
        "the SQL entity row is no longer written"
    )
    node = require_knowledge().get_by_key("Entity", entity.id)
    assert node is not None
    assert node.props["node_type"] == "legal.source"
    assert node.props["scope_key"] == "customer:1"
    assert node.props["name"] == entity.name


async def test_bare_entity_types_get_a_deterministic_namespaced_label(session):
    """Legacy adapters may use bare type names; the mirrored label must stay valid."""
    from app.services.knowledge.entities import knowledge_entity
    from app.services.knowledge.graph_entity_mirror import graph_node_type

    assert graph_node_type("person") == "knowledge.entity.person"
    assert graph_node_type("legal.source") == "legal.source"
    entity = knowledge_entity(customer_id=1, entity_type="person", key="nja-2005s142", name="HD")
    await persist_extracted_knowledge(session, entities=[entity])
    await session.flush()
    node = require_knowledge().get_by_key("Entity", entity.id)
    assert node is not None and node.props["node_type"] == "knowledge.entity.person"


async def test_relationships_become_graph_edges_without_inventing_contradictions(session):
    """SUPPORTED_BY mirrors to SUPPORTS; only a real CONTRADICTS relation mirrors as one."""
    from app.services.knowledge.entities import knowledge_entity
    from app.services.knowledge.relationships import knowledge_relationship
    from app.services.overgraph.labels import CONTRADICTS, SUPPORTS

    unit_id = await _document(session, "f")
    claim = _claim(unit_id)
    first = knowledge_entity(customer_id=1, entity_type="legal.source", key="urn:a", name="A")
    second = knowledge_entity(customer_id=1, entity_type="legal.source", key="urn:b", name="B")
    supported = knowledge_relationship(
        customer_id=1, relation="SUPPORTED_BY",
        from_kind="claim", from_id=claim.id,
        to_kind="entity", to_id=first.id,
    )
    contradicted = knowledge_relationship(
        customer_id=1, relation="CONTRADICTS",
        from_kind="entity", from_id=first.id,
        to_kind="entity", to_id=second.id,
    )
    await persist_extracted_knowledge(
        session, claims=[claim], entities=[first, second],
        relationships=[supported, contradicted],
    )
    await session.flush()

    catalog = require_knowledge()
    assert catalog.count_edges_by_label(SUPPORTS) >= 1
    assert catalog.count_edges_by_label(CONTRADICTS) == 1, "only the real contradiction is an edge"


async def test_unsupported_evidence_creates_no_contradiction_edge(session):
    """Accepted, unverified evidence must never produce a CONTRADICTS edge."""
    from app.services.overgraph.labels import CONTRADICTS

    unit_id = await _document(session, "g")
    await persist_extracted_knowledge(session, claims=[_claim(unit_id)])
    await session.flush()
    assert require_knowledge().count_edges_by_label(CONTRADICTS) == 0


async def test_research_observations_are_inventory_never_verification(session):
    """An observation about missing evidence must not verify a claim or contradict anything."""
    from app.services.knowledge.observations import ObservationSeed, knowledge_observation
    from app.services.knowledge.scope import require_persist_scope
    from app.services.overgraph.labels import CONTRADICTS

    await _document(session, "obs")
    observation = knowledge_observation(
        ObservationSeed(
            observation_class="source_quality",
            kind="passage_unsupported",
            document_id="doc-obs",
            document_version_id="ver-obs",
            statement_normalized="No passage supports the claimed notice period.",
        ),
        require_persist_scope(customer_id=1, scope_type="customer"),
    )
    catalog = require_knowledge()
    claims_before = catalog.count_nodes_by_labels(["Claim"])
    contradictions_before = catalog.count_edges_by_label(CONTRADICTS)

    await persist_extracted_knowledge(session, observations=[observation])
    await session.flush()

    assert catalog.count_nodes_by_labels(["Claim"]) == claims_before, "no claim may be minted"
    assert catalog.count_edges_by_label(CONTRADICTS) == contradictions_before
    observations = [
        row
        for engine_id in catalog.find_nodes("VerificationObservation", "kind", "passage_unsupported")
        if (row := catalog.get(engine_id)) is not None
    ]
    assert observations, "the observation must be inventoriable in the graph"
    assert not observations[0].props.get("decision"), "an observation carries no Jev verdict"


async def test_document_deletion_keeps_support_from_other_documents(session):
    """The real deletion path removes only that document's evidence links."""
    from app.database.models import DocumentVersionRecord
    from app.services.knowledge.persistence import delete_canonical_document
    from app.services.overgraph.legal_claims import evidence_links, legal_claim_key

    first = await _document(session, "a")
    second = await _document(session, "b")
    claim = _claim(first)
    await persist_extracted_knowledge(session, claims=[claim])
    await persist_extracted_knowledge(session, claims=[_claim(second)])
    await session.flush()

    catalog = require_knowledge()
    key = legal_claim_key(claim.scope, claim.predicate, claim.value)
    assert len(evidence_links(catalog, key)) == 2

    assert await session.get(DocumentVersionRecord, "ver-a") is not None
    await delete_canonical_document(session, "doc-a")
    await session.flush()

    remaining = [str(link.props["document_version_id"]) for link in evidence_links(catalog, key)]
    assert remaining == ["ver-b"]
    assert catalog.get_by_key("Claim", key) is not None


async def test_graph_audit_counts_match_the_sql_audit(session):
    """The graph-side audit counts agree with the SQL mirror while both exist."""
    from app.database.models import (
        KnowledgeClaimRecord,
        KnowledgeRelationshipRecord,
    )
    from app.services.knowledge.graph_audit import graph_audit_counts
    from app.services.knowledge.entities import knowledge_entity
    from app.services.knowledge.relationships import knowledge_relationship

    unit_id = await _document(session, "h")
    claim = _claim(unit_id)
    first = knowledge_entity(customer_id=1, entity_type="legal.source", key="urn:x", name="X")
    second = knowledge_entity(customer_id=1, entity_type="legal.source", key="urn:y", name="Y")
    edge = knowledge_relationship(
        customer_id=1, relation="CONTRADICTS",
        from_kind="entity", from_id=first.id, to_kind="entity", to_id=second.id,
    )
    await persist_extracted_knowledge(
        session, claims=[claim], entities=[first, second], relationships=[edge],
    )
    await session.flush()

    sql_claims = len(list((await session.execute(select(KnowledgeClaimRecord))).scalars().all()))
    assert sql_claims == 0, "claims live only in the graph now"
    sql_relationships = len(
        list((await session.execute(select(KnowledgeRelationshipRecord))).scalars().all())
    )
    graph = graph_audit_counts(require_knowledge())
    assert graph["claims"] == 1
    assert graph["entities"] == 2, "entities now live only in the graph"
    assert graph["contradicts_edges"] == 1
    assert sql_relationships == 0, "the SQL relationship row is no longer written"


async def test_observations_are_mirrored_under_the_domain_identity(session):
    """Graph observations use the domain id, so reuse detection cannot fork identities."""
    from app.services.knowledge.observations import ObservationSeed, knowledge_observation
    from app.services.knowledge.scope import require_persist_scope

    await _document(session, "i")
    observation = knowledge_observation(
        ObservationSeed(
            observation_class="source_quality",
            kind="passage_unsupported",
            document_id="doc-i",
            document_version_id="ver-i",
            statement_normalized="Ingen passage stöder påståendet.",
        ),
        require_persist_scope(customer_id=1, scope_type="customer"),
    )
    await persist_extracted_knowledge(session, observations=[observation])
    await session.flush()
    node = require_knowledge().get_by_key("VerificationObservation", observation.id)
    assert node is not None, "the graph node must use the domain observation id"
    assert node.props["scope_key"] == "customer:1"
    assert not node.props.get("decision")


async def test_customer_purge_removes_graph_observations():
    """Deleting a customer's knowledge must not leave observation inventory behind."""
    from app.services.kund_dokument import _delete_scope_nodes
    from app.services.overgraph.labels import VERIFICATION_OBSERVATION
    from app.services.overgraph.claims import (
        VerificationObservationWrite,
        observation_identity,
        upsert_verification_observation,
    )

    catalog = require_knowledge()
    from app.services.knowledge.scope import customer_scope

    scope = customer_scope(7)
    write = VerificationObservationWrite(
        class_id="source_quality", document_id="doc-p", document_version_id="ver-p",
        value={"statement": "Ingen passage stöder påståendet."},
        polarity="observed", taxonomy_version="research-observation-v1",
        scope=scope, kind="passage_unsupported", decision=None,
    )
    upsert_verification_observation(catalog, write)
    key = observation_identity(write)
    assert catalog.get_by_key("VerificationObservation", key) is not None

    await _delete_scope_nodes(VERIFICATION_OBSERVATION, 7)
    assert catalog.get_by_key("VerificationObservation", key) is None


async def test_entity_mirror_merges_extra_like_the_sql_update(session):
    """A reused entity keeps old attributes and gets the new ones, exactly like SQL."""
    from app.services.knowledge.entities import knowledge_entity

    first = knowledge_entity(
        customer_id=1, entity_type="legal.source", key="urn:merge",
        name="Avtalslagen", extra={"kind": "statute"},
    )
    await persist_extracted_knowledge(session, entities=[first])
    await session.flush()
    second = knowledge_entity(
        customer_id=1, entity_type="legal.source", key="urn:merge",
        name="Avtalslagen (1915:218)", extra={"chapter": 3},
    )
    await persist_extracted_knowledge(session, entities=[second])
    await session.flush()

    node = require_knowledge().get_by_key("Entity", second.id)
    import json

    assert json.loads(node.props["attributes_json"]) == {"kind": "statute", "chapter": 3}
    assert node.props["name"] == "Avtalslagen (1915:218)"


async def test_graph_entity_reader_matches_the_sql_lookup(session):
    """Reading an entity by (scope, id) finds the same node in both stores."""
    from app.services.knowledge.entities import knowledge_entity
    from app.services.knowledge.graph_entity_mirror import entity_in_graph

    entity = knowledge_entity(
        customer_id=1, entity_type="legal.court", key="nja-2005s142",
        name="Högsta domstolen", extra={"instance": "HD"},
    )
    await persist_extracted_knowledge(session, entities=[entity])
    await session.flush()

    graph = entity_in_graph(
        require_knowledge(), scope_key="customer:1", entity_id=entity.id,
    )
    assert graph is not None
    assert graph.key == entity.id
    assert graph.props["name"] == entity.name
    assert graph.props["node_type"] == entity.entity_type
    assert entity_in_graph(
        require_knowledge(), scope_key="customer:2", entity_id=entity.id,
    ) is None


async def test_graph_support_reader_matches_the_sql_claim_links(session):
    """The graph reports the same supporting TextUnits as the SQL claim links."""
    from app.services.overgraph.legal_claims import (
        legal_claim_key,
        supporting_text_units,
    )

    first = await _document(session, "a")
    second = await _document(session, "b")
    claim = _claim(first)
    claim = KnowledgeClaim(
        id=claim.id, customer_id=1, predicate=PREDICATE, value=VALUE,
        supporting_text_unit_ids=(first, second),
    )
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()

    key = legal_claim_key(claim.scope, claim.predicate, claim.value)
    graph_units = supporting_text_units(require_knowledge(), key)
    assert sorted(graph_units) == sorted([first, second])


async def test_supersession_is_visible_in_the_graph(session):
    """Closing a claim must set the graph status and validity window, not just SQL."""
    from app.services.knowledge.claims import supersede_knowledge_claim
    from app.services.overgraph.legal_claims import claim_is_superseded, legal_claim_key

    unit_id = await _document(session, "j")
    claim = _claim(unit_id)
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()

    key = legal_claim_key(claim.scope, claim.predicate, claim.value)
    assert claim_is_superseded(require_knowledge(), key) is False
    await supersede_knowledge_claim(session, claim.id)
    await session.flush()
    catalog = require_knowledge()
    assert claim_is_superseded(catalog, key) is True
    node = catalog.get_by_key("Claim", key)
    assert node.props["status"] == "superseded"
    assert node.props["valid_to_ms"] > 0
    assert "Claim" in node.labels, "history stays queryable"


async def test_claim_scope_reader_falls_back_to_the_graph(session):
    """A claim that exists only in the graph still resolves its tenant scope."""
    from app.services.knowledge.claims import _claim_scope
    from app.services.overgraph.legal_claims import legal_claim_key

    unit_id = await _document(session, "k")
    claim = _claim(unit_id)
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()
    key = legal_claim_key(claim.scope, claim.predicate, claim.value)
    resolved = await _claim_scope(session, key)
    assert resolved.scope_key == "customer:1"


async def test_claim_answer_links_are_mirrored_for_question_reuse(session):
    """Which claims answer a question must be answerable from the graph alone."""
    from app.services.knowledge.claims import (
        answer_research_need,
        claim_answers_for_question_key,
    )
    from app.services.overgraph.claim_answers import claim_answers_for_question
    from app.services.overgraph.legal_claims import legal_claim_key

    unit_id = await _document(session, "m")
    claim = _claim(unit_id)
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()
    await answer_research_need(
        session, research_need_id="need-1",
        question_key="q-shared", claim_ids=[claim.id], source_type="upload",
    )
    await session.flush()

    sql_hits = await claim_answers_for_question_key(
        session, customer_id=1, question_key="q-shared",
    )
    graph = claim_answers_for_question(
        require_knowledge(), customer_id=1, question_key="q-shared",
    )
    key = legal_claim_key(claim.scope, claim.predicate, claim.value)
    assert [hit.claim.id for hit in sql_hits] == [key]
    assert [str(node.key) for node in graph] == [key]


async def test_edges_to_text_units_and_documents_are_mirrored(session):
    """Every relationship kind now has a graph endpoint, so no edge needs a SQL-only row."""
    from app.services.knowledge.entities import knowledge_entity
    from app.services.knowledge.relationships import knowledge_relationship
    from app.services.overgraph.labels import DOCUMENT, SUPPORTS, LINKED

    unit_id = await _document(session, "n")
    claim = _claim(unit_id)
    court = knowledge_entity(customer_id=1, entity_type="legal.court", key="hd", name="HD")
    to_unit = knowledge_relationship(
        customer_id=1, relation="SUPPORTED_BY",
        from_kind="claim", from_id=claim.id, to_kind="text_unit", to_id=unit_id,
    )
    to_document = knowledge_relationship(
        customer_id=1, relation="ABOUT",
        from_kind="entity", from_id=court.id, to_kind="document", to_id="doc-n",
    )
    await persist_extracted_knowledge(
        session, claims=[claim], entities=[court], relationships=[to_unit, to_document],
    )
    await session.flush()

    catalog = require_knowledge()
    assert catalog.count_edges_by_label(SUPPORTS) >= 1
    assert catalog.count_edges_by_label(LINKED) >= 1
    assert catalog.get_by_key(DOCUMENT, "doc-n") is not None
    assert catalog.get_by_key("TextUnit", unit_id) is not None


async def test_two_text_units_with_the_same_assertion_stay_two_fact_nodes(session):
    """Additive contract: identical wording in another source unit is another fact."""
    from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
    from app.services.knowledge.scope import customer_scope
    from app.services.overgraph.catalogs import require_knowledge as catalog
    from app.services.overgraph.write import upsert_entity, write_fact

    scope = customer_scope(1)
    graph = catalog()
    for unit_suffix in ("1", "2"):
        await _document(session, f"fact-{unit_suffix}")
    source_key = upsert_entity(graph, NodeInput(
        node_type="legal.source", name="Avtalslagen", scope=scope,
    )).key
    target_key = upsert_entity(graph, NodeInput(
        node_type="legal.issue", name="Uppsägningstid", scope=scope,
    )).key
    first = write_fact(graph, FactInput(
        source_id=source_key, target_id=target_key, scope=scope,
        predicate="legal.rule", fact_text="Nio månaders uppsägningstid gäller.",
        sources=(SourceRef(kind="text_unit", ref="tu-fact-1"),),
    ))
    second = write_fact(graph, FactInput(
        source_id=source_key, target_id=target_key, scope=scope,
        predicate="legal.rule", fact_text="Nio månaders uppsägningstid gäller.",
        sources=(SourceRef(kind="text_unit", ref="tu-fact-2"),),
    ))
    assert first.key != second.key, "different source occurrences must be separate facts"
    assert graph.count_nodes_by_labels(["Fact"]) == 2
