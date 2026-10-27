"""Tenant Knowledge Owner vertical: ingest -> find -> Q&A reuse -> isolation."""

from __future__ import annotations

from app.services.document_find.request import FindRequest
from app.services.document_qa.access import Viewer
from app.services.document_qa.owner_document_index import classify_and_index
from app.services.document_qa.owner_find import run_find
from app.services.document_qa.owner_ingest import persist_document_units
from app.services.document_qa.owner_qa import persist
from app.services.document_qa.owner_qa_retrieve import exact_reuse
from app.services.document_qa.types import (
    AnalysisContract,
    AnswerPostWrite,
    QaWrite,
    SourceCite,
)
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_registry import tenant_owner_client

EMBEDDING = (1.0, 0.0, 0.0, 0.0)
CONTRACT = AnalysisContract(
    kind="document_chat", method="evidence_answer",
    model="test-model", model_version="v1",
)


def _unit(unit_id: str, document_id: str, text: str) -> TextUnitWrite:
    return TextUnitWrite(
        unit_id=unit_id,
        scope=customer_scope(1),
        document_id=document_id,
        document_version_id=f"{document_id}-ver",
        text=text,
        content_hash=f"hash-{unit_id}",
        ordinal=0,
        embedding=EMBEDDING,
    )


def _viewer(customer_id: int = 1) -> Viewer:
    return Viewer(
        customer_id=customer_id, workspace_id="ws-1",
        readable_document_ids=frozenset({"doc-a"}),
        readable_version_ids=frozenset({"doc-a-ver"}),
    )


async def _seed_document(client: OwnerClient, document_id: str, text: str) -> None:
    await persist_document_units(client, document_id=document_id, units=(
        _unit(f"{document_id}-unit", document_id, text),
    ))
    await classify_and_index(client, document_id=document_id, document_type="nda")


async def test_tenant_catalog_vertical_uses_only_the_owner(tenant_owners):
    client = await tenant_owners(1)
    assert tenant_owner_client(1) is client
    await _seed_document(client, "doc-a", "sekretessavtal om uppsägning")
    await _seed_document(client, "doc-b", "sekretessavtal om anställning")
    found = await run_find(
        client, FindRequest(customer_id=1, query="visa alla sekretessavtal", mode="replace"),
    )
    assert found.document_ids == ("doc-a", "doc-b")
    write = QaWrite(
        question_text="Vad gäller uppsägning?",
        document_id="doc-a",
        document_version_id="doc-a-ver",
        workspace_id="ws-1",
        contract=CONTRACT,
        status="ANSWERED",
        answer_text="Uppsägning regleras i avtalet.",
        posts=(AnswerPostWrite(
            text="Uppsägning regleras i avtalet.",
            sources=(SourceCite(
                text_unit_id="doc-a-unit", excerpt="sekretessavtal om uppsägning",
                start=0, end=10, position_validated=True,
            ),),
        ),),
        asked_at="2026-10-26T10:00:00Z",
        created_at="2026-10-26T10:00:00Z",
        embedding=EMBEDDING,
    )
    loaded = await persist(client, _viewer(), write)
    hit = await exact_reuse(
        client, _viewer(), question_text="Vad gäller uppsägning?",
        document_id="doc-a", document_version_id="doc-a-ver", contract=CONTRACT,
    )
    assert hit is not None and hit.answer.key == loaded.answers[0].key
    # A second client on the same owner sees the same data immediately.
    second = await tenant_owners(1)
    assert (await run_find(
        second, FindRequest(customer_id=1, query="visa alla sekretessavtal", mode="replace"),
    )).document_ids == ("doc-a", "doc-b")


async def test_tenant_catalogs_are_isolated_behind_their_owners(tenant_owners):
    first = await tenant_owners(1)
    second = await tenant_owners(2)
    await _seed_document(first, "doc-a", "sekretessavtal kund 1")
    await _seed_document(second, "doc-a", "sekretessavtal kund 2")
    assert (await run_find(
        first, FindRequest(customer_id=1, query="visa alla sekretessavtal", mode="replace"),
    )).document_ids == ("doc-a",)
    assert (await run_find(
        second, FindRequest(customer_id=2, query="visa alla sekretessavtal", mode="replace"),
    )).document_ids == ("doc-a",)
    assert await first.count_nodes("Question") == 0
    assert await second.count_nodes("Question") == 0
