"""Isolated A/B/C/D Tabular Review cache experiment.

A: product full-grid cache. B: same scoring, Top-K result persistence only.
C: vectorized scoring, Top-K. D (exploratory): vectorized scoring, no
persistent similarity cache. Same documents, embeddings, anchors and columns.
No Jev, no quality claim.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).parent))

from benchmark_tabular_review_real import (
    CANDIDATES,
    CATEGORIES,
    CUSTOMER_ID,
    ROOT,
    USER_ID,
    _ingest,
    _seed_anchors,
)
from app.config import settings
from app.database.base import Base
from app.database.models import Kund, UserAccount
from app.database.tabular_review import TabularReviewCandidate, TabularReviewScoreCache
from app.services.overgraph.catalogs import OverGraphRuntime, open_catalog, set_runtime
from app.services.tabular_review.ranking import ColumnScoreOptions, decide_cell, score_document_column
from app.services.tabular_review.run import fill_review
from app.services.tabular_review.store import add_column, create_review, persist_decision, require_review, set_documents
from app.services.tabular_review.types import ColumnSpec, RankedCandidate

OUT = ROOT / "backend" / "tests" / "integration" / "baselines" / "tabular-review-cache-arms-v1.json"
LIMIT = 5
ARMS = ("A", "B", "C", "D")
REPEATS = 2


def _columns(set_ids: dict[str, str], count: int) -> list[ColumnSpec]:
    return [
        ColumnSpec(column_id=None, title=category, anchor_set_id=set_ids[category], label=category, sort_order=index)
        for index, category in enumerate(CATEGORIES[:count])
    ]


async def _new_review(factory, docs: list[str], specs: list[ColumnSpec]) -> int:
    async with factory() as session:
        review = await create_review(session, customer_id=CUSTOMER_ID, created_by_user_id=USER_ID, name="Cache arms")
        await set_documents(session, review, docs)
        for spec in specs:
            await add_column(session, review, spec)
        await session.commit()
        return review.id


async def _actual_specs(factory, review_id: int, templates: list[ColumnSpec]) -> list[ColumnSpec]:
    async with factory() as session:
        review = await require_review(session, review_id, customer_id=CUSTOMER_ID)
        columns = sorted(review.columns, key=lambda item: item.sort_order)
        return [
            ColumnSpec(
                column_id=column.id,
                title=column.title,
                anchor_set_id=column.anchor_set_id,
                label=column.label,
                polarity=column.polarity,
                allow_abstain=column.allow_abstain,
                abstain_margin=column.abstain_margin,
                sort_order=column.sort_order,
            )
            for column in columns
        ]


def _vectorized(units, embeddings, anchor_vectors, spec) -> object:
    if not anchor_vectors:
        from app.services.tabular_review.types import NO_HIT, CellDecision
        return CellDecision(status=NO_HIT, selected=None, candidates=(), threshold=0.35, no_hit_reason="no_active_anchors")
    matrix = np.asarray([embeddings[unit.id] for unit in units if unit.id in embeddings], dtype=float)
    if matrix.size == 0:
        from app.services.tabular_review.types import NO_HIT, CellDecision
        return CellDecision(status=NO_HIT, selected=None, candidates=(), threshold=0.35, no_hit_reason="no_candidates")
    anchors = np.asarray(anchor_vectors, dtype=float)
    matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    anchors = anchors / np.linalg.norm(anchors, axis=1, keepdims=True)
    scores = (matrix @ anchors.T).max(axis=1)
    order = sorted(range(len(units)), key=lambda i: (-float(scores[i]), units[i].id))[:LIMIT]
    from app.services.tabular_review.locators import source_locator
    ranked = tuple(
        RankedCandidate(
            text_unit_id=units[i].id,
            exact_text=units[i].text,
            similarity=float(scores[i]),
            polarity=spec.polarity,
            source=source_locator(units[i]),
        )
        for i in order
    )
    return decide_cell(
        ranked, threshold=0.35, polarity=spec.polarity,
        allow_abstain=spec.allow_abstain, abstain_margin=spec.abstain_margin,
    )


def _decisions(units_by_doc, embeddings, anchors, specs, *, vectorized: bool, only_column: int | None = None):
    result = []
    for doc_id, units in units_by_doc.items():
        for spec in specs:
            if spec.column_id is None or (only_column is not None and spec.column_id != only_column):
                continue
            anchor_vectors = anchors[spec.column_id].vectors
            if vectorized:
                decision = _vectorized(units, embeddings[doc_id], anchor_vectors, spec)
            else:
                decision = score_document_column(
                    units, dict(embeddings[doc_id]), anchor_vectors,
                    ColumnScoreOptions(polarity=spec.polarity, threshold=0.35, limit=LIMIT),
                )
            result.append((doc_id, spec.column_id, decision))
    return result


async def _persist_decisions(factory, review_id: int, decisions, *, only_column: int | None = None):
    async with factory() as session:
        review = await require_review(session, review_id, customer_id=CUSTOMER_ID)
        rows = {row.document_id: row for row in review.rows}
        columns = {column.id: column for column in review.columns}
        for doc_id, column_id, decision in decisions:
            if only_column is not None and column_id != only_column:
                continue
            await persist_decision(
                session, review=review, row=rows[doc_id],
                column=columns[column_id], decision=decision,
            )
        review.computed_at = __import__("app.services.tabular_review.store", fromlist=["utcnow"]).utcnow()
        await session.commit()


async def _fill_custom(factory, review_id: int, units, embeddings, anchors, specs, *, vectorized, only_column=None):
    decisions = _decisions(units, embeddings, anchors, specs, vectorized=vectorized, only_column=only_column)
    await _persist_decisions(factory, review_id, decisions, only_column=only_column)


async def _warm_read(factory, review_id: int) -> None:
    async with factory() as session:
        review = await require_review(session, review_id, customer_id=CUSTOMER_ID)
        _ = [(cell.status, cell.text_unit_id) for cell in review.cells]
        await session.rollback()


async def _topk(factory, review_id: int) -> dict[tuple[str, int], list[tuple[str, float]]]:
    async with factory() as session:
        review = await require_review(session, review_id, customer_id=CUSTOMER_ID)
        rows = {row.id: row.document_id for row in review.rows}
        columns = {column.id: column.sort_order for column in review.columns}
        out = {}
        for cell in review.cells:
            candidates = list((await session.execute(
                select(TabularReviewCandidate).where(TabularReviewCandidate.cell_id == cell.id).order_by(TabularReviewCandidate.rank)
            )).scalars())
            out[(rows[cell.row_id], columns[cell.column_id])] = [(item.text_unit_id, round(float(item.similarity), 6)) for item in candidates[:LIMIT]]
        return out


def _p95(values: list[float]) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20)[18]


async def _run() -> dict:
    candidates = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    rows = candidates["rows"]
    temp = Path(tempfile.mkdtemp(prefix="cache-arms-"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{temp / 'arms.db'}")
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
        embeddings_by_document, units_by_document = await _ingest(factory, knowledge, rows)
        set_ids = _seed_anchors(knowledge, rows, units_by_document)
        # AnchorVectors are loaded by fill_review; custom arms need the same vectors.
        from app.services.tabular_review.run import load_anchor_vectors
        timings: dict[str, dict[str, list[float]]] = {arm: {"cold": [], "warm": [], "add": []} for arm in ARMS}
        reviews: dict[str, int] = {}
        cache_rows = {}
        for arm in ARMS:
            for _ in range(REPEATS):
                review_id = await _new_review(factory, list(units_by_document), _columns(set_ids, 4))
                actual_specs = await _actual_specs(factory, review_id, _columns(set_ids, 4))
                arm_anchors = load_anchor_vectors(knowledge, actual_specs)
                started = time.perf_counter()
                if arm == "A":
                    await fill_review(factory, review_id, catalog=knowledge, embeddings_by_document=embeddings_by_document, customer_id=CUSTOMER_ID)
                else:
                    await _fill_custom(factory, review_id, units_by_document, embeddings_by_document, arm_anchors, actual_specs, vectorized=arm in ("C", "D"))
                timings[arm]["cold"].append(time.perf_counter() - started)
                started = time.perf_counter()
                if arm == "A":
                    await fill_review(factory, review_id, catalog=knowledge, embeddings_by_document=embeddings_by_document, customer_id=CUSTOMER_ID)
                elif arm == "D":
                    await _fill_custom(factory, review_id, units_by_document, embeddings_by_document, arm_anchors, actual_specs, vectorized=True)
                else:
                    await _warm_read(factory, review_id)
                timings[arm]["warm"].append(time.perf_counter() - started)

                if arm == "A":
                    async with factory() as session:
                        await session.execute(delete(TabularReviewScoreCache))
                        await session.commit()
                add_review = await _new_review(factory, list(units_by_document), _columns(set_ids, 3))
                add_specs = await _actual_specs(factory, add_review, _columns(set_ids, 3))
                add_anchors = load_anchor_vectors(knowledge, add_specs)
                if arm == "A":
                    await fill_review(factory, add_review, catalog=knowledge, embeddings_by_document=embeddings_by_document, customer_id=CUSTOMER_ID)
                else:
                    await _fill_custom(factory, add_review, units_by_document, embeddings_by_document, add_anchors, add_specs, vectorized=arm in ("C", "D"))
                async with factory() as session:
                    review = await require_review(session, add_review, customer_id=CUSTOMER_ID)
                    await add_column(session, review, ColumnSpec(column_id=None, title=CATEGORIES[3], anchor_set_id=set_ids[CATEGORIES[3]], label=CATEGORIES[3], sort_order=3))
                    await session.commit()
                final_specs = await _actual_specs(factory, add_review, _columns(set_ids, 4))
                final_anchors = load_anchor_vectors(knowledge, final_specs)
                started = time.perf_counter()
                if arm == "A":
                    await fill_review(factory, add_review, catalog=knowledge, embeddings_by_document=embeddings_by_document, customer_id=CUSTOMER_ID)
                else:
                    await _fill_custom(factory, add_review, units_by_document, embeddings_by_document, final_anchors, final_specs, vectorized=arm in ("C", "D"), only_column=final_specs[-1].column_id)
                timings[arm]["add"].append(time.perf_counter() - started)
                reviews[arm] = review_id
            if arm == "A":
                async with factory() as session:
                    cache_rows[arm] = int((await session.execute(select(func.count()).select_from(TabularReviewScoreCache))).scalar_one())
            else:
                cache_rows[arm] = 0
        parity = {}
        arm_topk = {arm: await _topk(factory, reviews[arm]) for arm in ARMS}
        base = arm_topk["A"]
        for arm in ARMS:
            matches = 0
            total = 0
            for key, value in base.items():
                total += 1
                if arm_topk[arm].get(key) == value:
                    matches += 1
            parity[arm] = {"identical_top5_cells": matches, "cells": total}
        return {
            "kind": "cache_arms",
            "not_quality_measurement": True,
            "note": "Synthetic provisional anchors; result parity against A. D is exploratory.",
            "contracts": len(units_by_document),
            "text_units": sum(len(units) for units in units_by_document.values()),
            "columns": 4,
            "repeats": REPEATS,
            "timings": {
                arm: {phase: {"median": round(statistics.median(values), 3), "p95": round(_p95(values), 3)}
                      for phase, values in phases.items()}
                for arm, phases in timings.items()
            },
            "score_cache_rows": cache_rows,
            "result_cells": {arm: len(arm_topk[arm]) for arm in ARMS},
            "result_candidates": {arm: sum(len(value) for value in arm_topk[arm].values()) for arm in ARMS},
            "top5_parity": parity,
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
