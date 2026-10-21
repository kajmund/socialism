"""Tantivy fulltext index derived from OverGraph TextUnit and Fact nodes.

The index is a rebuildable search projection, never a second source of truth.
It supports BM25 fulltext with Swedish analysis, tenant/document filters, and
deterministic keyset pagination. Rebuilding reads TextUnits directly from the
OverGraph knowledge catalog.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import tantivy

from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.model import GraphRecord
from app.services.overgraph.labels import FACT, TEXT_UNIT
from app.services.tantivy_documents import (
    KIND_FACT,
    SV_ANALYZER,
    FactDoc,
    TextUnitDoc,
    _document,
    _fact,
    _fact_document,
    _unit,
    iter_facts,
    iter_text_units,
)
from app.services.tantivy_subwords import (
    MIN_QUERY_PART,
    SUBWORD_ANALYZER,
    SUBWORD_FIELD,
    _subword_analyzer,
    subword_parts as subword_parts,
)

INDEX_VERSION = "graph-index-v4"  # fact identity became source-anchored (source-fact-v1)
DEFAULT_WRITER_HEAP = 128_000_000
WATERMARK_FILE = "watermark.json"


def _swedish_analyzer() -> tantivy.TextAnalyzer:
    return (
        tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.simple())
        .filter(tantivy.Filter.lowercase())
        .filter(tantivy.Filter.stemmer("swedish"))
        .build()
    )


def build_schema() -> tantivy.Schema:
    builder = tantivy.SchemaBuilder()
    builder.add_text_field("key", stored=True, fast=True, tokenizer_name="raw", index_option="basic")
    builder.add_text_field("tenant_id", stored=True, tokenizer_name="raw", index_option="basic")
    builder.add_text_field("document_id", stored=True, tokenizer_name="raw", index_option="basic")
    builder.add_text_field("document_version_id", stored=True, tokenizer_name="raw", index_option="basic")
    builder.add_text_field("structure_id", stored=True, tokenizer_name="raw", index_option="basic")
    builder.add_text_field("content_hash", stored=True, tokenizer_name="raw", index_option="basic")
    builder.add_text_field("kind", stored=True, fast=True, tokenizer_name="raw", index_option="basic")
    builder.add_text_field("status", stored=True, tokenizer_name="raw", index_option="basic")
    builder.add_integer_field("valid_from_ms", stored=True, fast=True, indexed=True)
    builder.add_integer_field("valid_to_ms", stored=True, fast=True, indexed=True)
    builder.add_text_field("text", stored=True, tokenizer_name=SV_ANALYZER, index_option="position")
    builder.add_text_field(
        SUBWORD_FIELD, stored=False, tokenizer_name=SUBWORD_ANALYZER, index_option="position",
    )
    return builder.build()


@dataclass(frozen=True)
class FactHit:
    key: str
    tenant_id: str
    score: float


@dataclass(frozen=True)
class TextUnitHit:
    key: str
    document_id: str
    document_version_id: str
    text: str


@dataclass(frozen=True)
class SearchResult:
    hits: list[TextUnitHit]
    total: int


class TextUnitIndex:
    """Opens a built Tantivy index and serves fulltext queries."""

    def __init__(self, index: tantivy.Index, analyzer: tantivy.TextAnalyzer) -> None:
        self._index = index
        self._analyzer = analyzer

    @classmethod
    def open(cls, path: Path) -> TextUnitIndex:
        analyzer = _swedish_analyzer()
        index = tantivy.Index.open(str(path))
        index.register_tokenizer(SV_ANALYZER, analyzer)
        index.register_tokenizer(SUBWORD_ANALYZER, _subword_analyzer())
        index.reload()
        return cls(index, analyzer)

    def analyze(self, query: str) -> tuple[str, ...]:
        seen: list[str] = []
        for token in self._analyzer.analyze(query):
            if token and token not in seen:
                seen.append(token)
        return tuple(seen)

    def search(
        self,
        query: str,
        *,
        tenant_ids: tuple[str, ...] | None = None,
        document_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        order: tantivy.Order = tantivy.Order.Asc,
        kind: str | None = None,
    ) -> SearchResult:
        """BM25 fulltext with optional tenant/document filters, sorted by key."""
        if limit < 1:
            raise ValueError("fulltext search limit must be >= 1")
        terms = self.analyze(query)
        if not terms:
            return SearchResult(hits=[], total=0)
        searcher = self._index.searcher()
        query_object = _build_query(
            self._index.schema,
            terms,
            tenant_ids=tenant_ids,
            document_id=document_id,
            kind=kind,
        )
        result = searcher.search(
            query_object,
            limit=limit,
            count=True,
            order_by_field="key",
            offset=offset,
            order=order,
        )
        hits = [_hit(searcher, address) for _sort_value, address in result.hits]
        return SearchResult(hits=hits, total=int(result.count))

    def delete_keys(self, keys: tuple[str, ...]) -> None:
        """Remove documents by TextUnit key (used for incremental updates)."""
        writer = self._index.writer()
        try:
            for key in keys:
                writer.delete_documents_by_term("key", key)
            writer.commit()
        finally:
            writer.wait_merging_threads()
        self._index.reload()

    def search_fact_keys(
        self,
        query: str,
        *,
        tenant_ids: tuple[str, ...] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FactHit]:
        """BM25 lexical fact candidates, best first. Hydration happens in OverGraph."""
        if limit < 1:
            raise ValueError("fulltext search limit must be >= 1")
        terms = self.analyze(query)
        if not terms:
            return []
        searcher = self._index.searcher()
        query_object = _build_query(
            self._index.schema, terms, tenant_ids=tenant_ids, document_id=None, kind=KIND_FACT,
        )
        result = searcher.search(query_object, limit=limit + offset)
        hits: list[FactHit] = []
        for score, address in result.hits[offset:]:
            document = searcher.doc(address)
            hits.append(FactHit(
                key=str(document.get_first("key") or ""),
                tenant_id=str(document.get_first("tenant_id") or ""),
                score=float(score),
            ))
        return hits

    def search_subword_keys(
        self,
        query: str,
        *,
        tenant_ids: tuple[str, ...] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FactHit]:
        """Complementary sub-word matches. Ranked below direct BM25 hits by the caller."""
        if limit < 1:
            raise ValueError("fulltext search limit must be >= 1")
        terms = tuple(
            str(token).strip() for token in _subword_analyzer().analyze(query)
            if len(str(token).strip()) >= MIN_QUERY_PART
        )
        if not terms:
            return []
        searcher = self._index.searcher()
        should = [
            (
                tantivy.Occur.Should,
                tantivy.Query.term_query(
                    self._index.schema, SUBWORD_FIELD, term, index_option="basic",
                ),
            )
            for term in dict.fromkeys(terms)
        ]
        clauses: list[tuple[tantivy.Occur, tantivy.Query]] = [
            (tantivy.Occur.Must, tantivy.Query.boolean_query(should, minimum_number_should_match=1)),
        ]
        clauses.append(
            (tantivy.Occur.Must, tantivy.Query.term_query(self._index.schema, "kind", KIND_FACT, index_option="basic"))
        )
        if tenant_ids:
            clauses.append((
                tantivy.Occur.Must,
                tantivy.Query.or_should_match(*[
                    tantivy.Query.term_query(self._index.schema, "tenant_id", tenant, index_option="basic")
                    for tenant in tenant_ids
                ]),
            ))
        result = searcher.search(tantivy.Query.boolean_query(clauses), limit=limit + offset)
        hits: list[FactHit] = []
        for score, address in result.hits[offset:]:
            document = searcher.doc(address)
            hits.append(FactHit(
                key=str(document.get_first("key") or ""),
                tenant_id=str(document.get_first("tenant_id") or ""),
                score=float(score),
            ))
        return hits

    def upsert_facts(self, facts: Sequence[FactDoc]) -> None:
        """Add or replace fact documents by fact key (delete-then-add = idempotent)."""
        if not facts:
            return
        writer = self._index.writer()
        try:
            for fact in facts:
                writer.delete_documents_by_term("key", fact.key)
                writer.add_document(_fact_document(fact))
            writer.commit()
        finally:
            writer.wait_merging_threads()
        self._index.reload()

    def upsert_units(self, units: Sequence[TextUnitDoc]) -> None:
        """Add or replace documents by TextUnit key (delete-then-add = idempotent)."""
        if not units:
            return
        writer = self._index.writer()
        try:
            for unit in units:
                writer.delete_documents_by_term("key", unit.key)
                writer.add_document(_document(unit))
            writer.commit()
        finally:
            writer.wait_merging_threads()
        self._index.reload()


def _build_query(
    schema: tantivy.Schema,
    terms: tuple[str, ...],
    *,
    tenant_ids: tuple[str, ...] | None,
    document_id: str | None,
    kind: str | None = None,
) -> tantivy.Query:
    should = [(tantivy.Occur.Should, tantivy.Query.term_query(schema, "text", term)) for term in terms]
    clauses: list[tuple[tantivy.Occur, tantivy.Query]] = [
        (tantivy.Occur.Must, tantivy.Query.boolean_query(should, minimum_number_should_match=1)),
    ]
    if tenant_ids:
        clauses.append(
            (
                tantivy.Occur.Must,
                tantivy.Query.or_should_match(
                    *[
                        tantivy.Query.term_query(schema, "tenant_id", tenant, index_option="basic")
                        for tenant in tenant_ids
                    ]
                ),
            )
        )
    if kind is not None:
        clauses.append(
            (tantivy.Occur.Must, tantivy.Query.term_query(schema, "kind", kind, index_option="basic"))
        )
    if document_id is not None:
        clauses.append(
            (
                tantivy.Occur.Must,
                tantivy.Query.term_query(schema, "document_id", document_id, index_option="basic"),
            )
        )
    return tantivy.Query.boolean_query(clauses)


def _hit(searcher: tantivy.Searcher, address: object) -> TextUnitHit:
    document = searcher.doc(address)
    return TextUnitHit(
        key=str(document.get_first("key") or ""),
        document_id=str(document.get_first("document_id") or ""),
        document_version_id=str(document.get_first("document_version_id") or ""),
        text=str(document.get_first("text") or ""),
    )


def build_from_overgraph(
    catalog: Catalog,
    index_dir: Path,
    *,
    writer_heap_size: int = DEFAULT_WRITER_HEAP,
) -> TextUnitIndex:
    """Rebuild the index atomically from the OverGraph TextUnit nodes."""
    started = _now_ms()
    units = list(iter_text_units(catalog))
    facts = list(iter_facts(catalog))
    if not units and not facts:
        raise ValueError("cannot build a fulltext index from an empty graph")
    write_index_version(index_dir)
    target = Path(index_dir) / "current"
    tmp = Path(index_dir) / f".building-{os.getpid()}-{time.time_ns()}"
    tmp.mkdir(parents=True, exist_ok=True)

    schema = build_schema()
    analyzer = _swedish_analyzer()
    index = tantivy.Index(schema, path=str(tmp))
    index.register_tokenizer(SV_ANALYZER, analyzer)
    index.register_tokenizer(SUBWORD_ANALYZER, _subword_analyzer())
    writer = index.writer(heap_size=writer_heap_size, num_threads=0)
    for unit in units:
        writer.add_document(_document(unit))
    for fact in facts:
        writer.add_document(_fact_document(fact))
    writer.commit()
    writer.wait_merging_threads()
    del writer

    _atomic_swap(tmp, target)
    # The watermark is the build start time, so TextUnits updated mid-build are
    # re-indexed by the next reconcile instead of being silently missed.
    write_watermark(Path(index_dir), started)
    return TextUnitIndex.open(target)


def _atomic_swap(tmp: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.parent / f".old-{os.getpid()}-{time.time_ns()}"
        os.rename(target, backup)
        try:
            os.rename(tmp, target)
        except Exception:
            os.rename(backup, target)
            raise
        shutil.rmtree(backup, ignore_errors=True)
    else:
        os.rename(tmp, target)


def _now_ms() -> int:
    return int(time.time() * 1000)


def write_index_version(index_dir: Path) -> None:
    """Persist the schema/identity version next to the index."""
    target = Path(index_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "version.json").write_text(json.dumps({"version": INDEX_VERSION}))


def read_index_version(index_dir: Path) -> str:
    """The version the index on disk was built with (empty when unknown)."""
    path = Path(index_dir) / "version.json"
    if not path.exists():
        return ""
    return str(json.loads(path.read_text()).get("version") or "")


def read_watermark(index_dir: Path) -> int:
    """Highest OverGraph updated_at (ms) reflected in the index; 0 if unknown."""
    path = Path(index_dir) / WATERMARK_FILE
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("updated_at_ms", 0))
    except (ValueError, TypeError, OSError):
        return 0


def write_watermark(index_dir: Path, updated_at_ms: int) -> None:
    Path(index_dir).mkdir(parents=True, exist_ok=True)
    (Path(index_dir) / WATERMARK_FILE).write_text(
        json.dumps({"updated_at_ms": int(updated_at_ms)}) + "\n",
        encoding="utf-8",
    )


def pending_updates(
    catalog: Catalog, *, watermark_ms: int, now_ms: int | None = None,
) -> int:
    """Number of TextUnits updated after ``watermark_ms`` (0 = index is caught up)."""
    now = now_ms if now_ms is not None else _now_ms()
    return len(catalog.find_nodes_by_time_range(TEXT_UNIT, watermark_ms + 1, now)) + len(
        catalog.find_nodes_by_time_range(FACT, watermark_ms + 1, now)
    )


def reconcile(
    catalog: Catalog,
    index: TextUnitIndex,
    *,
    watermark_ms: int,
    now_ms: int | None = None,
    page_size: int = 1000,
) -> int:
    """Index TextUnits updated since ``watermark_ms``; return the new watermark.

    Idempotent and at-least-once: re-running over the same window is safe because
    ``add_document`` is key-based. A failed run leaves the old watermark, so the
    next run re-scans the same window. The returned watermark must be persisted by
    the caller only after this returns successfully.
    """
    now = now_ms if now_ms is not None else _now_ms()
    for label, upsert in ((TEXT_UNIT, _units_for), (FACT, _facts_for)):
        after: int | None = None
        while True:
            ids, after = catalog.find_nodes_by_time_range_paged(
                label, watermark_ms + 1, now, limit=page_size, after=after,
            )
            if not ids:
                break
            nodes = [node for node in catalog.get_nodes(ids) if node is not None]
            upsert(index, nodes)
            if after is None:
                break
    return now


def _units_for(index: TextUnitIndex, nodes: list[GraphRecord]) -> None:
    index.upsert_units([_unit(node) for node in nodes])


def _facts_for(index: TextUnitIndex, nodes: list[GraphRecord]) -> None:
    index.upsert_facts([_fact(node) for node in nodes])
