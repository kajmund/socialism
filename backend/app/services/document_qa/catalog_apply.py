"""Apply a claimed document_catalog_write after the outbox session is closed."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.graph_v2 import GraphIngestWork
from app.database.models import CanonicalDocumentRecord
from app.services.document_find import classify_and_index
from app.services.document_ingest_batch.progress import record_searchable
from app.services.document_qa.catalog_write import unit_writes, write_document_units
from app.services.document_qa.kinds import DOCUMENT_CATALOG_WRITE
from app.services.document_qa.outbox import require_owned_ids
from app.services.document_qa.tenants import require_tenant_catalogs
from app.services.graph_v2.errors import PermanentGraphError
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.units import TextUnit
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.text_units import load_domain_text_units


async def apply_document_catalog_work(
    factory: async_sessionmaker[AsyncSession],
    work_id: str,
    attempt: int,
    embedder: EmbeddingProvider,
) -> int:
    customer_id, document_id, version_id, units, title = await _load(factory, work_id)
    vectors = await embedder.embed([unit.text for unit in units])
    writes = unit_writes(units, customer_id=customer_id, embeddings=vectors)
    catalogs = require_tenant_catalogs()
    catalog = catalogs.open_for(customer_id)
    await write_document_units(catalog, document_id=document_id, units=writes)
    opening = units[0].text if units else ""
    headings = " ".join(unit.text for unit in units[:5])
    classify_and_index(
        catalog,
        document_id=document_id,
        title=title,
        opening=opening,
        headings=headings,
    )
    await record_searchable(
        factory,
        graph_work_id=work_id,
        document_id=document_id,
        document_version_id=version_id,
        unit_total=len(units),
    )
    return await _complete(factory, work_id, attempt)


async def _load(
    factory: async_sessionmaker[AsyncSession], work_id: str,
) -> tuple[int, str, str, tuple[TextUnit, ...], str]:
    async with factory.begin() as session:
        row = await session.get(GraphIngestWork, work_id)
        if row is None:
            raise PermanentGraphError("document_catalog_write row is missing")
        payload = dict(row.payload)
        if payload.get("kind") != DOCUMENT_CATALOG_WRITE:
            raise PermanentGraphError("document_catalog_write kind is missing")
        document_id = str(payload.get("document_id") or "")
        version_id = str(payload.get("document_version_id") or "")
        customer_id = row.customer_id
        await require_owned_ids(session, customer_id, document_id, version_id)
        document = await session.get(CanonicalDocumentRecord, document_id)
        title = document.title if document is not None else document_id
        units = tuple(await asyncio.to_thread(
            load_domain_text_units, require_knowledge(), document_version_id=version_id,
        ))
        if not units:
            raise PermanentGraphError("document catalog write has no TextUnits")
        return customer_id, document_id, version_id, units, title


async def _complete(
    factory: async_sessionmaker[AsyncSession], work_id: str, attempt: int,
) -> int:
    async with factory.begin() as session:
        result = await session.execute(update(GraphIngestWork).where(
            GraphIngestWork.id == work_id,
            GraphIngestWork.status == "processing",
            GraphIngestWork.attempts == attempt,
        ).values(
            status="completed",
            processed_at=datetime.now(UTC),
            retry_at=None,
            last_error=None,
        ))
    return int(result.rowcount == 1)
