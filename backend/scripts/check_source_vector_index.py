"""Time known source vectors in isolation using the configured real services."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.services.knowledge.embeddings import EmbeddingProvider
    from app.services.knowledge.vector_store import KnowledgeVectorStore


async def measure(
    factory: async_sessionmaker[AsyncSession], store: KnowledgeVectorStore,
    embeddings: EmbeddingProvider, *, document_id: str, write: bool,
) -> dict[str, object]:
    from app.services.knowledge.canonical_ingest import (
        _current_index_inputs, _embed_and_upsert, _index_has_text_units,
    )

    started = perf_counter()
    async with factory() as session:
        inputs = await _current_index_inputs(session, document_id)
    loaded = perf_counter()
    if len(inputs) != 1:
        raise ValueError("Document must have a persisted current version with TextUnits")
    document, units = inputs[0]
    present = await _index_has_text_units(
        store, document_id=document.document_id,
        document_version_id=units[0].document_version_id, units=units,
    )
    checked = perf_counter()
    if write:
        await _embed_and_upsert(
            document=document, units=units, embeddings=embeddings, vector_store=store,
        )
    written = perf_counter()
    if write and not await _index_has_text_units(
        store, document_id=document.document_id,
        document_version_id=units[0].document_version_id, units=units,
    ):
        raise RuntimeError("Projection write did not materialize all known vectors")
    return {
        "document_id": document.document_id,
        "document_version_id": units[0].document_version_id,
        "chunks": len(units), "present_before": present, "wrote_projection": write,
        "load_seconds": loaded - started, "get_seconds": checked - loaded,
        "embed_and_put_seconds": written - checked if write else None,
        "verify_seconds": perf_counter() - written if write else None,
    }


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.services.graph_v2.embeddings import GraphEmbeddingCacheProvider
    from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
    from app.services.knowledge.supabase_vector_client import start_supabase_vector_runtime
    from app.services.knowledge.vector_store import SupabaseVectorBucketStore

    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with AsyncExitStack() as cleanup:
        cleanup.push_async_callback(engine.dispose)
        runtime = await start_supabase_vector_runtime(settings)
        cleanup.push_async_callback(runtime.close)
        embeddings = GraphEmbeddingCacheProvider(factory, OpenAIEmbeddingProvider.from_settings())
        results = [await measure(
            factory, SupabaseVectorBucketStore(runtime.client), embeddings,
            document_id=args.document_id, write=args.write,
        ) for _ in range(args.repeat)]
        with Path(args.output).open("x", encoding="utf-8") as target:
            json.dump(results, target, ensure_ascii=False, indent=2)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return int(not args.write and any(not result["present_before"] for result in results))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", required=True, help="New report file; existing files are rejected")
    parser.add_argument("--write", action="store_true", help="Embed/cache and write current version keys")
    args = parser.parse_args()
    if not 1 <= args.repeat <= 100:
        parser.error("--repeat must be between 1 and 100")
    if Path(args.output).exists():
        parser.error("output file already exists")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
