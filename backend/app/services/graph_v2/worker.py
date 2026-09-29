"""Poll the durable Graph v2 outbox after research commits its evidence."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.graph_v2.outbox import process_graph_work
from app.services.graph_v2.revalidation import process_question_revalidation_work

logger = logging.getLogger(__name__)


async def run_graph_ingest_loop(factory: async_sessionmaker[AsyncSession]) -> None:
    while True:
        try:
            result = await process_graph_work(factory, limit=10)
            if result["completed"]:
                logger.info("graph_v2.ingest_batch completed=%s", result["completed"])
            async with factory.begin() as session:
                revalidation = await process_question_revalidation_work(session, limit=10)
            if revalidation["completed"]:
                logger.info(
                    "graph_v2.revalidation_batch completed=%s", revalidation["completed"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("graph_v2.worker_failed")
        await asyncio.sleep(5)


def start_graph_ingest_loop(factory: async_sessionmaker[AsyncSession]) -> asyncio.Task[None]:
    return asyncio.create_task(run_graph_ingest_loop(factory), name="graph-v2-ingest")


async def stop_graph_ingest_loop(task: asyncio.Task[None]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
