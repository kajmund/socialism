"""Canonical ingest must commit SQL before writing TextUnits to the Owner."""

from __future__ import annotations

import pytest

from app.database.models import Kund
from app.services.knowledge.canonical_ingest import ExtractedSourceIdentity, persist_extracted_source
from app.services.knowledge.persistence import write_segmented_document_text_units as real_owner_write
from app.services.knowledge.extractors import ExtractedBlock
from app.services.knowledge.models import KnowledgeDocument, KnowledgeScope
from tests.test_text_units import _extracted


def _document(*, customer_id: int) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id="order-doc",
        provider="test",
        external_id="ext-1",
        title="Order test",
        mime_type="text/plain",
        scope=KnowledgeScope(customer_id=customer_id, scope_type="customer"),
        version="v1",
        source_type="public_document",
        canonical_uri="https://example.test/order",
        metadata={},
    )


async def test_ingest_commits_sql_before_owner_text_units(
    client_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, factory = client_db
    order: list[str] = []
    async with factory() as session:
        kund = Kund(name="acme", slug="acme-order", available_modules=["dd"])
        session.add(kund)
        await session.flush()
        customer_id = kund.id

        real_commit = session.commit

        async def tracked_commit() -> None:
            order.append("sql_commit")
            await real_commit()

        async def tracked_owner_write(segmented, scope) -> None:
            order.append("owner_write")
            await real_owner_write(segmented, scope)

        monkeypatch.setattr(session, "commit", tracked_commit)
        monkeypatch.setattr(
            "app.services.knowledge.canonical_ingest.write_segmented_document_text_units",
            tracked_owner_write,
        )

        persisted = await persist_extracted_source(
            session,
            extracted=_extracted(
                ExtractedBlock(
                    text="Clause about termination.", locator="page:1", metadata={"page": 1},
                )
            ),
            document=_document(customer_id=customer_id),
            identity=ExtractedSourceIdentity(
                source_type="public_document",
                canonical_uri="https://example.test/order",
                content_hash="hash-order",
                customer_id=customer_id,
            ),
        )

    assert persisted.result.status == "indexed"
    assert order == ["sql_commit", "owner_write"]
