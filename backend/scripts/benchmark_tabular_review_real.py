"""Real (synthetic-corpus) Tabular Review performance bench.

Ingests the 35 candidate contracts into a temporary SQLite + Overgraph stack,
uses synthetic provisional anchors for the performance path only, and measures
cold/warm fill plus new-column reuse. Not a quality measurement: anchors are not
human-verified and UI/first-row streaming is not included.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Kund, UserAccount
from app.database.tabular_review import TabularReviewScoreCache
from app.services.clause_ssr.anchors import promote_anchor
from app.services.clause_ssr.classifications import upsert_classification
from app.services.clause_ssr.select import build_anchor_set
from app.services.clause_ssr.types import EmbeddingSpec
from app.services.clause_ssr.verifications import record_decision
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import TextUnit, hash_text
from app.services.overgraph.catalogs import OverGraphRuntime, open_catalog, set_runtime
from app.services.overgraph.text_units import upsert_text_units
from app.services.tabular_review.run import fill_review
from app.services.tabular_review.store import add_column, create_review, require_review, set_documents
from app.services.tabular_review.types import ColumnSpec

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = ROOT / "synthetic_sme" / "ground_truth" / "clause_review_candidates_v1.json"
OUT = ROOT / "backend" / "tests" / "integration" / "baselines" / "tabular-review-real-bench-v1.json"
CUSTOMER_ID = 1
USER_ID = "bench-user"
CATEGORIES = ("termination_notice", "automatic_renewal", "price", "liability_limitation")


def _paragraphs(path: Path) -> list[str]:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    result = []
    for paragraph in root.iter(f"{ns}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{ns}t")).strip()
        if text:
            result.append(text)
    return result


def _scope():
    return customer_scope(CUSTOMER_ID)


async def _ingest(factory, catalog, rows) -> dict[str, dict[int, list[float]]]:
    by_contract: dict[str, list[dict]] = {}
    for row in rows:
        by_contract.setdefault(row["contract_id"], []).append(row)
    provider = OpenAIEmbeddingProvider.from_settings()
    embeddings_by_document: dict[str, dict[int, list[float]]] = {}
    texts_all: list[str] = []
    units_by_document: dict[str, list[TextUnit]] = {}
    for contract_id, cards in by_contract.items():
        source = next((row for row in cards if row.get("source_path")), None)
        if source is None:
            continue
        path = ROOT / source["source_path"]
        paragraphs = _paragraphs(path)
        version_id = f"{contract_id}:v1"
        async with factory() as session:
            session.add(CanonicalDocumentRecord(
                id=contract_id, scope_type="customer", scope_key=f"customer:{CUSTOMER_ID}",
                customer_id=CUSTOMER_ID, source_type="synthetic", canonical_uri=f"contract://{contract_id}",
                title=cards[0].get("title") or contract_id, extra={},
            ))
            session.add(DocumentVersionRecord(
                id=version_id, scope_type="customer", scope_key=f"customer:{CUSTOMER_ID}",
                customer_id=CUSTOMER_ID, document_id=contract_id,
                content_hash=hash_text("\n".join(paragraphs)), mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                extra={},
            ))
            await session.commit()
        units = [
            TextUnit(
                id=f"{contract_id}:p{index}", document_version_id=version_id, document_id=contract_id,
                section_id=None, ordinal=index, text=text, content_hash=hash_text(text),
                locator=f"stycke {index + 1}",
            )
            for index, text in enumerate(paragraphs)
        ]
        texts_all.extend(unit.text for unit in units)
        units_by_document[contract_id] = units
    vectors = await provider.embed(texts_all) if texts_all else []
    cursor = 0
    for contract_id, units in units_by_document.items():
        count = len(units)
        doc_vectors = vectors[cursor:cursor + count]
        cursor += count
        upsert_text_units(catalog, units, scope=_scope(), embeddings=doc_vectors)
        embeddings_by_document[contract_id] = {
            unit.id: list(vector) for unit, vector in zip(units, doc_vectors, strict=True)
        }
    return embeddings_by_document, units_by_document


def _seed_anchors(catalog, rows, units_by_document) -> dict[str, str]:
    by_category: dict[str, int] = {}
    set_ids: dict[str, str] = {}
    embedding = EmbeddingSpec(
        model=settings.embedding_model,
        revision=settings.embedding_model_revision,
        dimension=settings.embedding_dimension,
    )
    for row in rows:
        if row["split"] != "anchor" or not row["generator_hint"]["present"]:
            continue
        category = row["category"]
        if by_category.get(category, 0) >= 3:
            continue
        unit = units_by_document[row["contract_id"]][row["candidate"]["paragraph_index"]]
        classification = upsert_classification(
            catalog, scope=_scope(), slug=category,
            question=f"Är det här en {category}-klausul?", category=category,
        )
        verification = record_decision(
            catalog, scope=_scope(), classification_id=classification.id,
            unit_id=unit.id, reviewer_id="synthetic-bench", answer="yes",
        )
        promote_anchor(catalog, verification.id, scope=_scope(), embedding=embedding)
        by_category[category] = by_category.get(category, 0) + 1
    for category in CATEGORIES:
        set_ids[category] = build_anchor_set(
            catalog, scope=_scope(), category=category, embedding=embedding,
        ).id
    return set_ids


async def _first_row_seconds(factory, catalog, *, units_by_document, embeddings_by_document, set_ids) -> float:
    first_contract = next(iter(units_by_document))
    async with factory() as session:
        review = await create_review(
            session, customer_id=CUSTOMER_ID, created_by_user_id=USER_ID,
            name="First row proxy",
        )
        await set_documents(session, review, [first_contract])
        for index, category in enumerate(CATEGORIES):
            await add_column(session, review, ColumnSpec(
                column_id=None, title=category, anchor_set_id=set_ids[category],
                label=category, sort_order=index,
            ))
        await session.commit()
        review_id = review.id
    started = time.perf_counter()
    await fill_review(
        factory, review_id, catalog=catalog,
        embeddings_by_document=embeddings_by_document, customer_id=CUSTOMER_ID,
    )
    return time.perf_counter() - started


async def _run() -> dict:
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    rows = candidates["rows"]
    temp = Path(tempfile.mkdtemp(prefix="tabular-bench-"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{temp / 'bench.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=CUSTOMER_ID, name="Bench", slug="bench", available_modules=["tabular_review"]))
        session.add(UserAccount(id=USER_ID, email="bench@local", role="user", kund_id=CUSTOMER_ID))
        await session.commit()
    knowledge = open_catalog(temp / "knowledge", kind="knowledge", dimension=settings.embedding_dimension)
    runtime = OverGraphRuntime(knowledge, open_catalog(temp / "memory", kind="memory", dimension=settings.embedding_dimension))
    set_runtime(runtime)
    try:
        ingest_started = time.perf_counter()
        embeddings_by_document, units_by_document = await _ingest(factory, knowledge, rows)
        ingest_seconds = time.perf_counter() - ingest_started
        set_ids = _seed_anchors(knowledge, rows, units_by_document)
        async with factory() as session:
            review = await create_review(
                session, customer_id=CUSTOMER_ID, created_by_user_id=USER_ID,
                name="Real bench",
            )
            await set_documents(session, review, list(units_by_document))
            for index, category in enumerate(CATEGORIES[:3]):
                await add_column(session, review, ColumnSpec(
                    column_id=None, title=category, anchor_set_id=set_ids[category],
                    label=category, sort_order=index,
                ))
            await session.commit()
            review_id = review.id
        cold_started = time.perf_counter()
        await fill_review(
            factory, review_id, catalog=knowledge,
            embeddings_by_document=embeddings_by_document, customer_id=CUSTOMER_ID,
        )
        cold_seconds = time.perf_counter() - cold_started
        warm_started = time.perf_counter()
        await fill_review(
            factory, review_id, catalog=knowledge,
            embeddings_by_document=embeddings_by_document, customer_id=CUSTOMER_ID,
        )
        warm_seconds = time.perf_counter() - warm_started
        async with factory() as session:
            review = await require_review(session, review_id, customer_id=CUSTOMER_ID)
            await add_column(session, review, ColumnSpec(
                column_id=None, title=CATEGORIES[3], anchor_set_id=set_ids[CATEGORIES[3]],
                label=CATEGORIES[3], sort_order=3,
            ))
            await session.commit()
        add_started = time.perf_counter()
        await fill_review(
            factory, review_id, catalog=knowledge,
            embeddings_by_document=embeddings_by_document, customer_id=CUSTOMER_ID,
        )
        add_seconds = time.perf_counter() - add_started
        async with factory() as session:
            cache_count = len((await session.execute(select(TabularReviewScoreCache))).scalars().all())
        first_row_seconds = await _first_row_seconds(
            factory,
            knowledge,
            units_by_document=units_by_document,
            embeddings_by_document=embeddings_by_document,
            set_ids=set_ids,
        )
        return {
            "kind": "real_synthetic_corpus",
            "not_quality_measurement": True,
            "note": "Synthetic provisional anchors; no human facit; no Jev. UI/first-row streaming not measured.",
            "contracts": len(units_by_document),
            "text_units": sum(len(units) for units in units_by_document.values()),
            "ingest_seconds": round(ingest_seconds, 3),
            "cold_fill_seconds": round(cold_seconds, 3),
            "warm_fill_seconds": round(warm_seconds, 3),
            "add_column_fill_seconds": round(add_seconds, 3),
            "first_row_proxy_seconds": round(first_row_seconds, 3),
            "first_row_proxy_note": "one contract x four columns, backend fill; not UI paint time",
            "cache_rows": cache_count,
            "embedding_model": settings.embedding_model,
        }
    finally:
        set_runtime(None)
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    payload = asyncio.run(_run())
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
