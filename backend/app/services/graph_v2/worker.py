"""Poll the durable Graph v2 outbox after research commits its evidence."""

import asyncio
import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.services.document_qa.owner import attach_graph_owner, detach_graph_owner
from app.services.graph_v2.outbox import process_graph_work

logger = logging.getLogger(__name__)


async def run_graph_ingest_loop(
    factory: async_sessionmaker[AsyncSession], *,
    kinds: Sequence[str] | None = None,
) -> None:
    while True:
        try:
            if kinds is None:
                result = await process_graph_work(factory, limit=10)
            else:
                result = await process_graph_work(factory, limit=10, kinds=kinds)
            if result["completed"]:
                logger.info("graph_v2.ingest_batch completed=%s", result["completed"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("graph_v2.worker_failed")
        await asyncio.sleep(5)


def start_graph_ingest_loop(
    factory: async_sessionmaker[AsyncSession], *,
    kinds: Sequence[str] | None = None,
) -> asyncio.Task[None]:
    return asyncio.create_task(
        run_graph_ingest_loop(factory, kinds=kinds), name="graph-v2-ingest",
    )


async def stop_graph_ingest_loop(task: asyncio.Task[None]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def start_graph_owner(factory: async_sessionmaker[AsyncSession]) -> asyncio.Task[None] | None:
    if not settings.graph_ingest_loop_enabled:
        return None
    attach_graph_owner()
    return start_graph_ingest_loop(factory)


async def stop_graph_owner(task: asyncio.Task[None] | None) -> None:
    if task is not None:
        await stop_graph_ingest_loop(task)
    detach_graph_owner()
