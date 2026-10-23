"""Fill a Tabular Review from SSR cosine matches. No Jev or LLM."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database.tabular_review import TabularReviewScoreCache
from app.services.clause_ssr.anchors import anchor_is_matchable, get_anchor
from app.services.clause_ssr.select import get_anchor_set
from app.serializers import utcnow
from app.services.knowledge.units import TextUnit
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.text_units import load_domain_text_units
from app.services.tabular_review.cache import ScoreCacheIdentity, score_cache_key
from app.services.tabular_review.locators import source_locator
from app.services.tabular_review.ranking import (
    ColumnScoreOptions,
    decide_cell,
    rank_candidates,
    score_document_column,
    unit_similarity,
)
from app.services.tabular_review.store import (
    cached_scores,
    get_review,
    load_inputs,
    persist_decision,
    put_cached_scores,
)
from app.services.tabular_review.types import (
    DEFAULT_CANDIDATE_LIMIT,
    CellDecision,
    ColumnSpec,
    DocumentRow,
    RankedCandidate,
    ReviewInputs,
)

SessionFactory = async_sessionmaker[AsyncSession]
UnitEmbeddings = Mapping[str, Mapping[str, list[float]]]


@dataclass(frozen=True)
class AnchorVectors:
    anchor_set_id: str
    version: str
    pool_revision: int
    label: str
    vectors: tuple[tuple[float, ...], ...]
    statements: tuple[str, ...]


def load_anchor_vectors(
    catalog: Catalog, columns: Sequence[ColumnSpec]
) -> dict[int, AnchorVectors]:
    """Read published clause anchor sets and their stored vectors from Overgraph."""
    loaded: dict[int, AnchorVectors] = {}
    for spec in columns:
        if spec.column_id is None:
            continue
        anchor_set = get_anchor_set(catalog, spec.anchor_set_id)
        if anchor_set.status != "active":
            raise ValueError(f"anchor set {spec.anchor_set_id} is not active")
        anchors = []
        for member_id in anchor_set.member_ids:
            anchor = get_anchor(catalog, member_id)
            if anchor.polarity != spec.polarity:
                continue
            if anchor.vector is None or not anchor_is_matchable(catalog, anchor):
                continue
            anchors.append(anchor)
        vectors = tuple(tuple(anchor.vector) for anchor in anchors if anchor.vector is not None)
        loaded[spec.column_id] = AnchorVectors(
            anchor_set_id=anchor_set.id,
            version=str(anchor_set.version),
            pool_revision=_membership_revision(anchor_set.member_ids),
            label=anchor_set.category,
            vectors=vectors,
            statements=tuple(anchor.provenance.get("question", "") for anchor in anchors),
        )
    return loaded


def _membership_revision(member_ids: Sequence[str]) -> int:
    digest = hashlib.sha256("\n".join(sorted(member_ids)).encode()).hexdigest()
    return int(digest[:8], 16)


def load_document_units(catalog: Catalog, document: DocumentRow) -> list[TextUnit]:
    return load_domain_text_units(catalog, document_version_id=document.document_version_id)


def _identity(
    unit: TextUnit,
    spec: ColumnSpec,
    anchors: AnchorVectors,
    *,
    embedding_model: str,
) -> ScoreCacheIdentity:
    return ScoreCacheIdentity(
        text_unit_id=unit.id,
        content_hash=unit.content_hash,
        anchor_set_id=anchors.anchor_set_id,
        anchor_set_version=anchors.version,
        pool_revision=anchors.pool_revision,
        embedding_model=embedding_model,
        label=spec.label,
        polarity=spec.polarity,
    )


def _cache_keys(
    units: Sequence[TextUnit],
    spec: ColumnSpec,
    anchors: AnchorVectors,
    *,
    embedding_model: str,
) -> list[str]:
    return [
        score_cache_key(_identity(unit, spec, anchors, embedding_model=embedding_model))
        for unit in units
    ]


def _decision_from_cache(
    units: Sequence[TextUnit],
    spec: ColumnSpec,
    *,
    embeddings: Mapping[str, list[float]],
    anchors: AnchorVectors,
    threshold: float,
    cache: Mapping[str, float],
    embedding_model: str,
) -> CellDecision:
    scored: list[RankedCandidate] = []
    for unit in units:
        key = score_cache_key(_identity(unit, spec, anchors, embedding_model=embedding_model))
        if key in cache:
            similarity = cache[key]
        elif unit.id in embeddings and anchors.vectors:
            similarity = unit_similarity(embeddings[unit.id], anchors.vectors)
        else:
            continue
        scored.append(
            RankedCandidate(
                text_unit_id=unit.id,
                exact_text=unit.text,
                similarity=similarity,
                polarity=spec.polarity,
                source=source_locator(unit),
            )
        )
    if not anchors.vectors:
        return CellDecision(
            status="no_hit",
            selected=None,
            candidates=(),
            threshold=threshold,
            no_hit_reason="no_active_anchors",
        )
    ranked = rank_candidates(scored, limit=DEFAULT_CANDIDATE_LIMIT)
    return decide_cell(
        ranked,
        threshold=threshold,
        polarity=spec.polarity,
        allow_abstain=spec.allow_abstain,
        abstain_margin=spec.abstain_margin,
    )


def score_inputs(
    inputs: ReviewInputs,
    *,
    units_by_document: Mapping[str, Sequence[TextUnit]],
    embeddings_by_document: UnitEmbeddings,
    anchors: Mapping[int, AnchorVectors],
    cache: Mapping[str, float],
) -> list[tuple[str, int, CellDecision]]:
    results: list[tuple[str, int, CellDecision]] = []
    for document in inputs.documents:
        units = units_by_document.get(document.document_id, ())
        embeddings = embeddings_by_document.get(document.document_id, {})
        for spec in inputs.columns:
            if spec.column_id is None:
                continue
            if (document.document_id, spec.column_id) in inputs.locked_cell_keys:
                continue
            column_anchors = anchors[spec.column_id]
            if cache:
                decision = _decision_from_cache(
                    units,
                    spec,
                    embeddings=embeddings,
                    anchors=column_anchors,
                    threshold=inputs.score_threshold,
                    cache=cache,
                    embedding_model=inputs.embedding_model,
                )
            else:
                decision = score_document_column(
                    units,
                    dict(embeddings),
                    column_anchors.vectors,
                    ColumnScoreOptions(
                        polarity=spec.polarity,
                        threshold=inputs.score_threshold,
                        allow_abstain=spec.allow_abstain,
                        abstain_margin=spec.abstain_margin,
                    ),
                )
            results.append((document.document_id, spec.column_id, decision))
    return results


def unscored_unit_ids(
    inputs: ReviewInputs,
    *,
    units_by_document: Mapping[str, Sequence[TextUnit]],
    embeddings_by_document: UnitEmbeddings,
    anchors: Mapping[int, AnchorVectors],
    cache: Mapping[str, float],
) -> list[str]:
    """Units that have neither an embedding nor a cache hit for every column."""
    columns = [spec for spec in inputs.columns if spec.column_id is not None]
    if not columns:
        return []
    missing: list[str] = []
    for document in inputs.documents:
        embeddings = embeddings_by_document.get(document.document_id, {})
        for unit in units_by_document.get(document.document_id, ()):
            if unit.id in embeddings:
                continue
            cached = all(
                score_cache_key(
                    _identity(
                        unit,
                        spec,
                        anchors[spec.column_id],
                        embedding_model=inputs.embedding_model,
                    )
                )
                in cache
                for spec in columns
            )
            if not cached:
                missing.append(f"{document.document_id}:{unit.id}")
    return missing


def new_cache_rows(
    inputs: ReviewInputs,
    *,
    units_by_document: Mapping[str, Sequence[TextUnit]],
    embeddings_by_document: UnitEmbeddings,
    anchors: Mapping[int, AnchorVectors],
    existing: Mapping[str, float],
) -> list[TabularReviewScoreCache]:
    rows: list[TabularReviewScoreCache] = []
    now = utcnow()
    for document in inputs.documents:
        units = units_by_document.get(document.document_id, ())
        embeddings = embeddings_by_document.get(document.document_id, {})
        for spec in inputs.columns:
            if spec.column_id is None:
                continue
            column_anchors = anchors[spec.column_id]
            for unit in units:
                key = score_cache_key(
                    _identity(unit, spec, column_anchors, embedding_model=inputs.embedding_model)
                )
                if key in existing or unit.id not in embeddings or not column_anchors.vectors:
                    continue
                rows.append(
                    TabularReviewScoreCache(
                        cache_key=key,
                        text_unit_id=unit.id,
                        content_hash=unit.content_hash,
                        anchor_set_id=column_anchors.anchor_set_id,
                        anchor_set_version=column_anchors.version,
                        pool_revision=column_anchors.pool_revision,
                        embedding_model=inputs.embedding_model,
                        label=spec.label,
                        polarity=spec.polarity,
                        similarity=unit_similarity(embeddings[unit.id], column_anchors.vectors),
                        updated_at=now,
                    )
                )
    return rows


async def fill_review(
    factory: SessionFactory,
    review_id: int,
    *,
    catalog: Catalog,
    embeddings_by_document: UnitEmbeddings,
    customer_id: int,
) -> ReviewInputs:
    """Score with the SQL connection released during embedding and ranking."""
    async with factory() as session:
        review = await get_review(session, review_id)
        if review is None or review.customer_id != customer_id:
            raise ValueError("review_not_found")
        inputs = await load_inputs(session, review, embedding_model=settings.embedding_model)
        await session.commit()

    anchors = load_anchor_vectors(catalog, inputs.columns)
    units_by_document = {
        document.document_id: load_document_units(catalog, document)
        for document in inputs.documents
    }
    cache_keys = [
        key
        for document in inputs.documents
        for spec in inputs.columns
        if spec.column_id is not None
        for key in _cache_keys(
            units_by_document[document.document_id],
            spec,
            anchors[spec.column_id],
            embedding_model=inputs.embedding_model,
        )
    ]
    async with factory() as session:
        cache = await cached_scores(session, cache_keys)
        await session.commit()

    missing = unscored_unit_ids(
        inputs,
        units_by_document=units_by_document,
        embeddings_by_document=embeddings_by_document,
        anchors=anchors,
        cache=cache,
    )
    if missing:
        raise RuntimeError(f"text unit embeddings missing: {', '.join(missing)}")

    decisions = score_inputs(
        inputs,
        units_by_document=units_by_document,
        embeddings_by_document=embeddings_by_document,
        anchors=anchors,
        cache=cache,
    )
    fresh = new_cache_rows(
        inputs,
        units_by_document=units_by_document,
        embeddings_by_document=embeddings_by_document,
        anchors=anchors,
        existing=cache,
    )

    async with factory() as session:
        review = await get_review(session, review_id)
        if review is None:
            raise ValueError("review_not_found")
        rows_by_document = {row.document_id: row for row in review.rows}
        columns_by_id = {column.id: column for column in review.columns}
        for document_id, column_id, decision in decisions:
            persist_row = rows_by_document[document_id]
            persist_column = columns_by_id[column_id]
            await persist_decision(
                session,
                review=review,
                row=persist_row,
                column=persist_column,
                decision=decision,
            )
        await put_cached_scores(session, fresh)
        review.computed_at = utcnow()
        review.updated_at = utcnow()
        await session.commit()
    return inputs
