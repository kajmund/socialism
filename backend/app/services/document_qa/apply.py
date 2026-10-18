"""Apply a claimed document_qa_write after the outbox session is closed."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.database.graph_v2 import GraphIngestWork
from app.services.document_qa.outbox import qa_from_payload, require_owned_version
from app.services.document_qa.store import persist
from app.services.document_qa.tenants import require_tenant_catalogs
from app.services.graph_v2.errors import PermanentGraphError


async def apply_document_qa_work(
    factory: async_sessionmaker[AsyncSession], work_id: str, attempt: int,
) -> int:
    async with factory.begin() as session:
        row = await session.get(GraphIngestWork, work_id)
        if row is None:
            raise PermanentGraphError("document_qa_write row is missing")
        customer_id = row.customer_id
        payload = dict(row.payload)
        try:
            viewer, write = qa_from_payload(payload, customer_id)
        except (ValueError, TypeError, KeyError) as exc:
            raise PermanentGraphError("document_qa_write payload is invalid") from exc
        await require_owned_version(session, customer_id, write)
    catalogs = require_tenant_catalogs()
    await asyncio.to_thread(persist, catalogs.open_for(customer_id), viewer, write)
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
