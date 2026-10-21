"""Fresh parity gate for the destructive Alembic drop.

A previously approved fingerprint is not proof: the database or the knowledge catalog may
have changed since. The drop therefore re-runs the full parity check against the database
and catalog as they are at migration time, and aborts with a clear error when anything is
missing from OverGraph.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import EMBEDDING_MODEL_DIMENSIONS, settings
from app.services.knowledge.verify_graph_parity import verify_parity
from app.services.overgraph.catalogs import (
    catalog_root,
    get_runtime,
    open_runtime,
    set_runtime,
)


class GraphParityError(RuntimeError):
    """The SQL knowledge tables are not fully represented in OverGraph."""


def knowledge_catalog_directory() -> Path:
    return Path(catalog_root(settings.overgraph_dir))


async def require_parity(database_url: str) -> dict[str, object]:
    """Run the parity check now. Raises ``GraphParityError`` unless everything matches."""
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    opened_here = False
    if get_runtime() is None:
        runtime = open_runtime(
            catalog_root(settings.overgraph_dir),
            knowledge_dimension=settings.embedding_dimension,
            memory_dimension=EMBEDDING_MODEL_DIMENSIONS[settings.mem0_embedding_model],
        )
        set_runtime(runtime)
        opened_here = True
    try:
        async with factory() as session:
            report = await verify_parity(session)
    finally:
        await engine.dispose()
        if opened_here:
            set_runtime(None)
    if not report.verified:
        details = "; ".join(report.mismatches[:10])
        raise GraphParityError(
            "refusing to drop the SQL knowledge tables: OverGraph parity failed "
            f"({len(report.mismatches)} mismatch(es), e.g. {details})"
        )
    return report.as_dict()


def require_parity_sync(database_url: str) -> dict[str, object]:
    return asyncio.run(require_parity(database_url))
