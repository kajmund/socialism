"""Enqueue a durable tenant-catalog write. This module never opens OverGraph."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphIngestWork
from app.services.document_qa.access import require_customer_id
from app.services.document_qa.kinds import DOCUMENT_CATALOG_WRITE
from app.services.document_qa.outbox import require_owned_ids
from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.identity import stable_id


async def enqueue_document_catalog(
    session: AsyncSession,
    *,
    customer_id: int,
    document_id: str,
    document_version_id: str,
    workspace_id: str = "",
) -> str:
    customer_id = require_customer_id(customer_id)
    if not document_id or not document_version_id:
        raise PermanentGraphError("document catalog write is missing version identity")
    await require_owned_ids(session, customer_id, document_id, document_version_id)
    work_id = stable_id(DOCUMENT_CATALOG_WRITE, str(customer_id), document_version_id)
    payload = {
        "kind": DOCUMENT_CATALOG_WRITE,
        "document_id": document_id,
        "document_version_id": document_version_id,
        "workspace_id": workspace_id,
    }
    try:
        async with session.begin_nested():
            session.add(GraphIngestWork(
                id=work_id,
                customer_id=customer_id,
                scope_key=f"customer:{customer_id}",
                payload=payload,
                status="pending",
                attempts=0,
            ))
            await session.flush()
    except IntegrityError:
        if await session.get(GraphIngestWork, work_id) is None:
            raise
    return work_id
