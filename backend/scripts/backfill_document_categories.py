"""Backfill DocumentCategory index for documents already in a tenant OverGraph.

Use when TextUnits exist but effective_type / DocumentCategory edges were never
written (find_documents returns empty_category). Stops at classification +
index only — does not re-embed.

Requires exclusive tenant lock: stop the API process that holds tenants/<id>/tenant.lock
before running.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.services.document_find import classify_and_index
from app.services.document_find.category_index import documents_for_type
from app.services.document_find.classify import classify_document
from app.services.document_find.labels import CANONICAL_DOCUMENT
from app.services.document_find.taxonomy import DOCUMENT_TYPES, TYPE_LABELS_SV
from app.services.document_qa.tenants import TenantCatalogs


async def _load_catalog_documents(customer_id: int) -> list[tuple[str, str]]:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        select distinct on (w.payload->>'document_id')
                          w.payload->>'document_id' as document_id,
                          c.title as title
                        from graph_ingest_work w
                        join canonical_documents c
                          on c.id = w.payload->>'document_id'
                        where w.customer_id = :customer_id
                          and w.payload->>'kind' = 'document_catalog_write'
                          and w.status = 'completed'
                        order by w.payload->>'document_id', w.processed_at desc nulls last
                        """
                    ),
                    {"customer_id": customer_id},
                )
            ).mappings().all()
    finally:
        await engine.dispose()
    return [(str(row["document_id"]), str(row["title"] or row["document_id"])) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer-id", type=int, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and report without writing to OverGraph.",
    )
    args = parser.parse_args()
    documents = asyncio.run(_load_catalog_documents(args.customer_id))
    if not documents:
        raise SystemExit(f"no completed document_catalog_write rows for customer {args.customer_id}")

    catalogs = TenantCatalogs(
        Path(settings.overgraph_dir),
        dimension=settings.embedding_dimension,
    )
    try:
        catalog = catalogs.open_for(args.customer_id)
        classified: Counter[str] = Counter()
        missing = 0
        written = 0
        for document_id, title in documents:
            if catalog.get_by_key(CANONICAL_DOCUMENT, document_id) is None:
                missing += 1
                print(f"skip missing graph node {document_id[:12]} {title}")
                continue
            if args.dry_run:
                document_type = classify_document(title=title, opening="", headings="")
            else:
                document_type = classify_and_index(
                    catalog,
                    document_id=document_id,
                    title=title,
                    opening="",
                    headings="",
                )
            classified[document_type] += 1
            written += 1
            print(f"{document_type:32} {title}")
        summary = {
            "customer_id": args.customer_id,
            "candidates": len(documents),
            "indexed": written,
            "missing_in_graph": missing,
            "dry_run": args.dry_run,
            "by_type": {
                TYPE_LABELS_SV.get(key, key): count
                for key, count in sorted(classified.items())
            },
            "category_sizes": {},
        }
        if not args.dry_run:
            summary["category_sizes"] = {
                TYPE_LABELS_SV.get(document_type, document_type): len(
                    documents_for_type(catalog, document_type)
                )
                for document_type in DOCUMENT_TYPES
                if documents_for_type(catalog, document_type)
            }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        catalogs.close()


if __name__ == "__main__":
    main()
