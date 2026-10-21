"""Tantivy BM25 over already-ingested TextUnits.

The index is a read-only experiment artifact. It is built from the published
TextUnits, verified against their stable keys/content hashes, and never used
to write back to OverGraph.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tantivy

from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit

SV_STEM = "sv_stem_v1"
SV_PLAIN = "sv_plain_v1"
ANALYZERS = (SV_STEM, SV_PLAIN)
BM25_K1 = 1.2
BM25_B = 0.75
INDEX_VERSION = "bm25-index-v1"
DEFAULT_WRITER_HEAP = 128_000_000
MANIFEST_NAME = "bm25-index-manifest.json"


@dataclass(frozen=True)
class Bm25Profile:
    name: str
    tokenizer: str = "simple"
    lowercase: bool = True
    stemmer: str | None = None
    stopwords: tuple[str, ...] = ()

    def analyzer(self) -> tantivy.TextAnalyzer:
        builder = tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.simple())
        if self.lowercase:
            builder = builder.filter(tantivy.Filter.lowercase())
        if self.stemmer:
            builder = builder.filter(tantivy.Filter.stemmer(self.stemmer))
        if self.stopwords:
            builder = builder.filter(tantivy.Filter.custom_stopword(list(self.stopwords)))
        return builder.build()

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "tokenizer": self.tokenizer,
            "lowercase": self.lowercase,
            "stemmer": self.stemmer,
            "stopwords": list(self.stopwords),
            "index_and_query_same_analyzer": True,
        }


def build_profile(name: str) -> Bm25Profile:
    if name == SV_STEM:
        return Bm25Profile(name=name, stemmer="swedish")
    if name == SV_PLAIN:
        return Bm25Profile(name=name, stemmer=None)
    raise ValueError(f"unknown BM25 analyzer profile {name!r}")


def build_schema(profile: Bm25Profile) -> tantivy.Schema:
    builder = tantivy.SchemaBuilder()
    builder.add_text_field(
        "key", stored=True, tokenizer_name="raw", index_option="basic"
    )
    builder.add_text_field(
        "document_id", stored=True, tokenizer_name="raw", index_option="basic"
    )
    builder.add_text_field(
        "collection_id", stored=True, tokenizer_name="raw", index_option="basic"
    )
    builder.add_text_field(
        "relative_path", stored=True, tokenizer_name="raw", index_option="basic"
    )
    builder.add_text_field(
        "document_version_id", stored=True, tokenizer_name="raw", index_option="basic"
    )
    builder.add_text_field(
        "content_hash", stored=True, tokenizer_name="raw", index_option="basic"
    )
    builder.add_text_field(
        "text", stored=True, tokenizer_name=profile.name, index_option="position"
    )
    return builder.build()


@dataclass(frozen=True)
class TieInfo:
    requested: int
    returned: int
    extra_fetched: int = 0
    tie_boundary_score: float | None = None
    tie_policy: str = "overfetch_until_score_boundary"
    empty_query: bool = False


@dataclass(frozen=True)
class Bm25Search:
    hits: list[SearchHit]
    terms: tuple[str, ...]
    tie: TieInfo


@dataclass
class Bm25Index:
    path: Path
    profile: Bm25Profile
    index: tantivy.Index
    searcher: tantivy.Searcher
    schema: tantivy.Schema
    analyzer: tantivy.TextAnalyzer
    manifest: dict[str, object] = field(default_factory=dict)

    def analyze(self, query: str) -> tuple[str, ...]:
        seen: set[str] = set()
        terms: list[str] = []
        for token in self.analyzer.analyze(query):
            if token and token not in seen:
                seen.add(token)
                terms.append(token)
        return tuple(terms)

    def search(
        self,
        query: str,
        *,
        limit: int,
        document_id: str | None = None,
        collection_id: str | None = None,
        terms: Sequence[str] | None = None,
    ) -> Bm25Search:
        if limit < 1:
            raise ValueError("BM25 search limit must be >= 1")
        analyzed = tuple(terms) if terms is not None else self.analyze(query)
        if not analyzed:
            return Bm25Search(
                hits=[],
                terms=(),
                tie=TieInfo(requested=limit, returned=0, empty_query=True),
            )
        query_object = build_query(
            self.schema,
            analyzed,
            document_id=document_id,
            collection_id=collection_id,
        )
        assert query_object is not None
        return _search_with_ties(
            self.searcher,
            query_object,
            limit=limit,
            terms=analyzed,
        )


def build_index(
    units: Sequence[StoredUnit],
    *,
    profile: Bm25Profile,
    index_dir: Path,
    rebuild: bool = False,
    writer_heap_size: int = DEFAULT_WRITER_HEAP,
    writer_num_threads: int = 0,
    verify_units: bool = True,
) -> Bm25Index:
    unit_list = list(units)
    _validate_units(unit_list)
    units_meta = units_metadata(unit_list)
    root = index_dir / profile.name / str(units_meta["units_hash_root"])[:16]
    index_dir.mkdir(parents=True, exist_ok=True)
    if root.exists():
        if not rebuild:
            existing = open_index(
                root,
                profile=profile,
                units=unit_list if verify_units else None,
                expected_units_meta=units_meta,
            )
            (root / "units.sha256").write_text(
                "\n".join(units_manifest_lines(unit_list)) + "\n",
                encoding="utf-8",
            )
            existing.manifest.setdefault("units", {})["sidecar"] = "units.sha256"
            _write_manifest(root, existing.manifest)
            return existing
        _remove_index_dir(root, index_dir)

    tmp = index_dir / profile.name / f".building-{os.getpid()}-{time.time_ns()}"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True)
    build_started = time.perf_counter()
    schema = build_schema(profile)
    analyzer = profile.analyzer()
    index = tantivy.Index(schema, path=str(tmp))
    index.register_tokenizer(profile.name, analyzer)
    writer = index.writer(
        heap_size=writer_heap_size,
        num_threads=writer_num_threads,
    )
    for unit in unit_list:
        writer.add_document(_document(unit))
    commit_opstamp = writer.commit()
    writer.wait_merging_threads()
    build_seconds = time.perf_counter() - build_started
    os.replace(tmp, root)
    (root / "units.sha256").write_text(
        "\n".join(units_manifest_lines(unit_list)) + "\n",
        encoding="utf-8",
    )

    opened = open_index(
        root,
        profile=profile,
        units=unit_list if verify_units else None,
        expected_units_meta=units_meta,
        build_info={
            "build_seconds": build_seconds,
            "commit_opstamp": commit_opstamp,
            "writer_heap_size": writer_heap_size,
            "writer_num_threads": writer_num_threads,
        },
    )
    opened.manifest["units"]["sidecar"] = "units.sha256"
    _write_manifest(root, opened.manifest)
    return opened


def open_index(
    path: Path,
    *,
    profile: Bm25Profile,
    units: Sequence[StoredUnit] | None = None,
    expected_units_meta: dict[str, object] | None = None,
    build_info: dict[str, object] | None = None,
) -> Bm25Index:
    manifest_path = path / MANIFEST_NAME
    if not manifest_path.is_file():
        if build_info is None:
            raise RuntimeError(
                f"BM25 index {path} has no manifest; rebuild with --bm25-rebuild-index"
            )
        manifest: dict[str, object] = {}
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_manifest(manifest, profile=profile, expected=expected_units_meta)
    index = tantivy.Index.open(str(path))
    analyzer = profile.analyzer()
    index.register_tokenizer(profile.name, analyzer)
    index.reload()
    searcher = index.searcher()
    result = Bm25Index(
        path=path,
        profile=profile,
        index=index,
        searcher=searcher,
        schema=index.schema,
        analyzer=analyzer,
        manifest=manifest,
    )
    verification_started = time.perf_counter()
    if units is not None:
        verify_index(result, units)
    verification_seconds = time.perf_counter() - verification_started
    if build_info is not None:
        manifest = {
            "version": INDEX_VERSION,
            "profile": profile.describe(),
            "tantivy_version": str(tantivy.__version__),
            "schema_fields": list(_schema_fields()),
            "bm25": {
                "k1": BM25_K1,
                "b": BM25_B,
                "source": "Tantivy default BM25",
                "tuned_on_gold": False,
            },
            "units": expected_units_meta or {},
            "index": {
                "path": str(path),
                "bytes": _dir_size(path),
                "files_hash": _dir_hash(path),
                **build_info,
                "verification_seconds": verification_seconds,
                "verified_units": None if units is None else len(units),
            },
            "verification": {
                "count_ok": units is not None,
                "keys_ok": units is not None,
                "content_hashes_ok": units is not None,
                "texts_ok": units is not None,
                "verified_units": None if units is None else len(units),
            },
            "created_at": datetime.now(UTC).isoformat(),
        }
        result.manifest = manifest
        _write_manifest(path, manifest)
    else:
        result.manifest = manifest
    return result


def verify_index(index: Bm25Index, units: Sequence[StoredUnit]) -> None:
    expected = {unit.key: unit for unit in units}
    if len(expected) != len(units):
        raise RuntimeError("duplicate TextUnit keys in materialized units")
    searcher = index.searcher
    if searcher.num_docs != len(unit_list := list(units)):
        raise RuntimeError(
            f"BM25 index has {searcher.num_docs} documents, expected {len(unit_list)}"
        )
    result = searcher.search(tantivy.Query.all_query(), limit=len(units) + 1, count=True)
    if result.count != len(units):
        raise RuntimeError(
            f"BM25 index reports {result.count} documents, expected {len(units)}"
        )
    seen: set[str] = set()
    for _score, address in result.hits:
        document = searcher.doc(address)
        key = str(document.get_first("key") or "")
        unit = expected.get(key)
        if unit is None:
            raise RuntimeError(f"BM25 index contains unknown TextUnit key {key!r}")
        if document.get_first("content_hash") != unit.content_hash:
            raise RuntimeError(f"BM25 index content_hash mismatch for {key}")
        if document.get_first("document_id") != unit.document_id:
            raise RuntimeError(f"BM25 index document_id mismatch for {key}")
        if document.get_first("text") != unit.text:
            raise RuntimeError(f"BM25 index text mismatch for {key}")
        seen.add(key)
    if seen != set(expected):
        missing = sorted(set(expected) - seen)
        raise RuntimeError(f"BM25 index is missing TextUnit keys: {missing[:5]}")


def build_query(
    schema: tantivy.Schema,
    terms: Sequence[str],
    *,
    document_id: str | None = None,
    collection_id: str | None = None,
) -> tantivy.Query | None:
    if not terms:
        return None
    should = [
        (tantivy.Occur.Should, tantivy.Query.term_query(schema, "text", term))
        for term in terms
    ]
    text_query = tantivy.Query.boolean_query(should, minimum_number_should_match=1)
    clauses: list[tuple[tantivy.Occur, tantivy.Query]] = [
        (tantivy.Occur.Must, text_query)
    ]
    if document_id is not None:
        clauses.append(
            (
                tantivy.Occur.Must,
                tantivy.Query.term_query(schema, "document_id", document_id),
            )
        )
    if collection_id is not None:
        clauses.append(
            (
                tantivy.Occur.Must,
                tantivy.Query.term_query(schema, "collection_id", collection_id),
            )
        )
    return tantivy.Query.boolean_query(clauses)


def units_manifest_lines(units: Sequence[StoredUnit]) -> list[str]:
    rows = []
    for unit in sorted(units, key=lambda item: item.key):
        text_hash = hashlib.sha256(unit.text.encode("utf-8")).hexdigest()
        rows.append(f"{unit.key}\t{unit.content_hash}\t{text_hash}")
    return rows


def units_metadata(units: Sequence[StoredUnit]) -> dict[str, object]:
    rows = []
    for unit in sorted(units, key=lambda item: item.key):
        text_hash = hashlib.sha256(unit.text.encode("utf-8")).hexdigest()
        rows.append(f"{unit.key}\0{unit.content_hash}\0{text_hash}")
    versions = sorted(
        {
            str(unit.props.get("document_version_id") or "")
            for unit in units
            if unit.props.get("document_version_id")
        }
    )
    document_ids = sorted({unit.document_id for unit in units})
    return {
        "count": len(units),
        "documents": len({unit.relative_path for unit in units}),
        "document_versions": len(versions),
        "units_hash_root": _sha256_text("\n".join(rows)),
        "document_ids_hash": _sha256_text("\n".join(document_ids)),
        "document_versions_hash": _sha256_text("\n".join(versions)),
    }


def _search_with_ties(
    searcher: tantivy.Searcher,
    query: tantivy.Query,
    *,
    limit: int,
    terms: Sequence[str],
) -> Bm25Search:
    first = searcher.search(query, limit=limit, count=True)
    if first.count == 0:
        return Bm25Search(
            hits=[],
            terms=tuple(terms),
            tie=TieInfo(requested=limit, returned=0),
        )
    result = first
    extra = 0
    if first.count > limit and len(first.hits) >= limit:
        result = searcher.search(query, limit=limit + 1, count=True)
        while (
            len(result.hits) > limit
            and result.hits[limit - 1][0] == result.hits[limit][0]
            and len(result.hits) < result.count
        ):
            next_limit = min(
                result.count,
                max(len(result.hits) * 2, limit + 1),
            )
            result = searcher.search(query, limit=next_limit, count=True)
        extra = max(0, len(result.hits) - limit)
    tie_boundary = result.hits[limit - 1][0] if len(result.hits) >= limit else None
    ordered = sorted(result.hits, key=lambda item: (-float(item[0]), _address_key(searcher, item[1])))
    hits: list[SearchHit] = []
    for rank, (score, address) in enumerate(ordered[:limit], start=1):
        document = searcher.doc(address)
        key = str(document.get_first("key") or "")
        hits.append(
            SearchHit(
                node_id=-1,
                key=key,
                score=float(score),
                rank=rank,
                document_id=str(document.get_first("document_id") or ""),
                relative_path=str(document.get_first("relative_path") or ""),
                text=str(document.get_first("text") or ""),
            )
        )
    return Bm25Search(
        hits=hits,
        terms=tuple(terms),
        tie=TieInfo(
            requested=limit,
            returned=len(hits),
            extra_fetched=extra,
            tie_boundary_score=None if tie_boundary is None else float(tie_boundary),
        ),
    )


def hydrate_hits(
    index: Bm25Index,
    hits: Sequence[SearchHit],
    *,
    by_key: dict[str, StoredUnit],
) -> list[SearchHit]:
    hydrated: list[SearchHit] = []
    for hit in hits:
        unit = by_key.get(hit.key)
        if unit is None:
            raise RuntimeError(f"BM25 hit {hit.key!r} is not in materialized units")
        hydrated.append(
            SearchHit(
                node_id=unit.node_id,
                key=unit.key,
                score=hit.score,
                rank=hit.rank,
                document_id=unit.document_id,
                relative_path=unit.relative_path,
                text=unit.text,
            )
        )
    return hydrated


def _document(unit: StoredUnit) -> tantivy.Document:
    document = tantivy.Document()
    document.add_text("key", unit.key)
    document.add_text("document_id", unit.document_id)
    document.add_text("collection_id", unit.collection_id)
    document.add_text("relative_path", unit.relative_path)
    document.add_text("document_version_id", str(unit.props.get("document_version_id") or ""))
    document.add_text("content_hash", unit.content_hash)
    document.add_text("text", unit.text)
    return document


def _address_key(searcher: tantivy.Searcher, address: Any) -> str:
    document = searcher.doc(address)
    return str(document.get_first("key") or "")


def _validate_units(units: Sequence[StoredUnit]) -> None:
    if not units:
        raise ValueError("cannot build a BM25 index from zero TextUnits")
    keys = [unit.key for unit in units]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate TextUnit keys in materialized units")
    for unit in units:
        if not unit.key:
            raise ValueError("TextUnit is missing a stable key")
        if not unit.document_id:
            raise ValueError(f"TextUnit {unit.key} is missing document_id")


def _validate_manifest(
    manifest: dict[str, object],
    *,
    profile: Bm25Profile,
    expected: dict[str, object] | None,
) -> None:
    if manifest.get("version") != INDEX_VERSION:
        raise RuntimeError(f"unsupported BM25 index version {manifest.get('version')!r}")
    stored_profile = manifest.get("profile") or {}
    if not isinstance(stored_profile, dict) or stored_profile.get("name") != profile.name:
        raise RuntimeError(
            f"BM25 index profile mismatch: {stored_profile.get('name')!r} != {profile.name!r}"
        )
    if expected is None:
        return
    stored_units = manifest.get("units") or {}
    if not isinstance(stored_units, dict):
        raise TypeError("BM25 index manifest has invalid units section")
    if stored_units.get("units_hash_root") != expected.get("units_hash_root"):
        raise RuntimeError(
            "BM25 index units_hash_root does not match current OverGraph TextUnits; "
            "rebuild with --bm25-rebuild-index"
        )
    if stored_units.get("count") != expected.get("count"):
        raise RuntimeError("BM25 index unit count does not match current OverGraph")


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    (path / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _remove_index_dir(path: Path, index_dir: Path) -> None:
    resolved = path.resolve()
    root = index_dir.resolve()
    if root not in resolved.parents:
        raise RuntimeError(f"refusing to remove index outside {root}: {resolved}")
    shutil.rmtree(path)


def _dir_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _dir_hash(path: Path) -> str:
    rows = []
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        relative = item.relative_to(path).as_posix()
        if relative == MANIFEST_NAME:
            continue
        rows.append(f"{relative}\0{hashlib.sha256(item.read_bytes()).hexdigest()}")
    return _sha256_text("\n".join(rows))


def _schema_fields() -> tuple[str, ...]:
    return (
        "key",
        "document_id",
        "collection_id",
        "relative_path",
        "document_version_id",
        "content_hash",
        "text",
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
