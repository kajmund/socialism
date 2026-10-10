"""Sequential ingest: discover, extract, segment, write, verify, publish."""

from __future__ import annotations

import resource
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from overgraph_ingest.config import IngestConfig
from overgraph_ingest.extraction import extract_file, load_extracted, store_extracted
from overgraph_ingest.extraction.model import ExtractedDocument
from overgraph_ingest.graph.builder import GraphDraft, build_graph
from overgraph_ingest.graph.schema import (
    DOCUMENT,
    STATUS_FAILED_PERMANENT,
    STATUS_PUBLISHED,
    STATUS_WRITING,
    TEXT_UNIT,
)
from overgraph_ingest.graph.stats import WriteStats, collect_structure_stats
from overgraph_ingest.graph.verifier import canonical_source, verify_document
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.ids import document_id, document_version_id, hash_file
from overgraph_ingest.segmentation.structural import SegmentedDocument, segment_document

SUPPORTED = {".pdf", ".docx"}


@dataclass(frozen=True)
class SourceFile:
    path: Path
    relative_path: str
    source_hash: str


@dataclass
class DocumentOutcome:
    relative_path: str
    document_id: str
    document_version_id: str
    status: str
    error: str | None
    pages: int
    chars: int
    text_units: int
    timings: dict[str, float] = field(default_factory=dict)
    error_class: str | None = None
    nodes: int = 0
    edges: int = 0
    structures: int = 0
    clauses: int = 0
    split_structures: int = 0
    split_text_units: int = 0
    oversized_units: int = 0
    exclusions: int = 0
    exclusion_reasons: list[str] = field(default_factory=list)
    text_unit_sizes: list[int] = field(default_factory=list)
    coverage: float = 0.0
    reconstructed: bool = False
    write_batches: list[dict[str, object]] = field(default_factory=list)


@dataclass
class PreparedDocument:
    source: SourceFile
    document_id: str
    document_version_id: str
    extracted: ExtractedDocument
    segmented: SegmentedDocument | None
    draft: GraphDraft | None
    timings: dict[str, float] = field(default_factory=dict)
    error: str | None = None


@dataclass
class RunReport:
    collection_id: str
    outcomes: list[DocumentOutcome]
    total_seconds: float
    peak_rss_bytes: int
    disk_bytes: int
    stage_seconds: dict[str, float]
    finalize_seconds: dict[str, float] = field(default_factory=dict)
    publish_ready_seconds: float = 0.0
    write_batches: list[dict[str, object]] = field(default_factory=list)
    node_upserts: int = 0
    edge_upserts: int = 0


def discover(input_dir: Path) -> list[SourceFile]:
    sources: list[SourceFile] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        sources.append(
            SourceFile(
                path=path,
                relative_path=path.relative_to(input_dir).as_posix(),
                source_hash=hash_file(path),
            )
        )
    return sources


def discover_limited(input_dir: Path, limit: int | None) -> list[SourceFile]:
    sources = discover(input_dir)
    if limit is None:
        return sources
    return sources[:limit]


def run_ingest(config: IngestConfig) -> RunReport:
    if config.input_dir is None:
        raise ValueError("--input is required")
    sources = discover_limited(config.input_dir, config.limit)
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    cache_dir = config.resolved_cache_dir()
    db = open_database(config.db_path, dimension)
    started = time.perf_counter()
    stage_seconds = {
        "extract": 0.0,
        "segment": 0.0,
        "build": 0.0,
        "write": 0.0,
        "write_nodes": 0.0,
        "write_edges": 0.0,
        "verify": 0.0,
        "publish": 0.0,
    }
    outcomes: list[DocumentOutcome] = []
    write_batches: list[dict[str, object]] = []
    node_upserts = 0
    edge_upserts = 0
    finalize = {"end_ingest": 0.0, "sync": 0.0}
    publish_ready = 0.0
    try:
        db.ingest_mode()
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        for source in sources:
            outcome = _ingest_one(config, writer, cache_dir, source)
            outcomes.append(outcome)
            for name, seconds in outcome.timings.items():
                stage_seconds[name] = stage_seconds.get(name, 0.0) + seconds
            write_batches.extend(outcome.write_batches)
            node_upserts += outcome.nodes
            edge_upserts += outcome.edges
        publish_ready = time.perf_counter() - started
        _, finalize["end_ingest"] = _timed(db.end_ingest)
        _, finalize["sync"] = _timed(db.sync)
    finally:
        db.close()
    return RunReport(
        collection_id=config.collection_id,
        outcomes=outcomes,
        total_seconds=time.perf_counter() - started,
        peak_rss_bytes=_peak_rss_bytes(),
        disk_bytes=_dir_size(config.db_path),
        stage_seconds=stage_seconds,
        finalize_seconds=finalize,
        publish_ready_seconds=publish_ready,
        write_batches=write_batches,
        node_upserts=node_upserts,
        edge_upserts=edge_upserts,
    )


def prepare_documents(config: IngestConfig) -> list[PreparedDocument]:
    if config.input_dir is None:
        raise ValueError("--input is required")
    cache_dir = config.resolved_cache_dir()
    prepared: list[PreparedDocument] = []
    for source in discover_limited(config.input_dir, config.limit):
        prepared.append(_prepare_one(config, cache_dir, source))
    return prepared


def write_prepared(config: IngestConfig, prepared: list[PreparedDocument]) -> RunReport:
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    db = open_database(config.db_path, dimension)
    started = time.perf_counter()
    stage_seconds = {
        "extract": 0.0,
        "segment": 0.0,
        "build": 0.0,
        "write": 0.0,
        "write_nodes": 0.0,
        "write_edges": 0.0,
        "verify": 0.0,
        "publish": 0.0,
    }
    outcomes: list[DocumentOutcome] = []
    write_batches: list[dict[str, object]] = []
    node_upserts = 0
    edge_upserts = 0
    finalize = {"end_ingest": 0.0, "sync": 0.0}
    publish_ready = 0.0
    try:
        db.ingest_mode()
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        for item in prepared:
            if item.draft is None or item.segmented is None:
                outcome = _fail_prepared(writer, config, item)
            else:
                outcome = _write_prepared_one(config, writer, item)
            outcomes.append(outcome)
            for name, seconds in outcome.timings.items():
                stage_seconds[name] = stage_seconds.get(name, 0.0) + seconds
            write_batches.extend(outcome.write_batches)
            node_upserts += outcome.nodes
            edge_upserts += outcome.edges
        publish_ready = time.perf_counter() - started
        _, finalize["end_ingest"] = _timed(db.end_ingest)
        _, finalize["sync"] = _timed(db.sync)
    finally:
        db.close()
    return RunReport(
        collection_id=config.collection_id,
        outcomes=outcomes,
        total_seconds=time.perf_counter() - started,
        peak_rss_bytes=_peak_rss_bytes(),
        disk_bytes=_dir_size(config.db_path),
        stage_seconds=stage_seconds,
        finalize_seconds=finalize,
        publish_ready_seconds=publish_ready,
        write_batches=write_batches,
        node_upserts=node_upserts,
        edge_upserts=edge_upserts,
    )


def run_verify(config: IngestConfig) -> list[str]:
    """Check that a closed database still has reconstructable published documents."""
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    db = open_database(config.db_path, dimension)
    errors: list[str] = []
    try:
        writer = GraphWriter(db, batch_size=config.write_batch_size)
        cache_dir = config.resolved_cache_dir()
        units_by_version: dict[str, list] = {}
        for node in writer.iter_nodes(TEXT_UNIT):
            version_id = str(node.props.get("document_version_id") or "")
            units_by_version.setdefault(version_id, []).append(node)
        for view in writer.iter_nodes(DOCUMENT):
            props = dict(view.props)
            if props.get("status") != STATUS_PUBLISHED:
                continue
            version_id = str(props.get("document_version_id") or "")
            stored = sorted(
                units_by_version.get(version_id, []),
                key=lambda node: int(node.props["sequence"]),
            )
            expected = int(props.get("persisted_text_units") or 0)
            if len(stored) != expected:
                errors.append(
                    f"{view.key}: stored {len(stored)} text units, expected {expected}"
                )
            reconstructed = "".join(str(node.props.get("text") or "") for node in stored)
            source_hash = str(props.get("source_hash") or "")
            extracted = load_extracted(cache_dir, source_hash, config.extraction_version)
            if extracted is None:
                errors.append(f"{view.key}: extraction cache missing")
                continue
            if reconstructed != canonical_source(extracted):
                errors.append(
                    f"{view.key}: stored TextUnits do not reconstruct the extracted source"
                )
    finally:
        db.close()
    return errors


def _ingest_one(
    config: IngestConfig,
    writer: GraphWriter,
    cache_dir: Path,
    source: SourceFile,
) -> DocumentOutcome:
    doc_id = document_id(config.collection_id, source.relative_path)
    version_id = document_version_id(doc_id, source.source_hash)
    timings: dict[str, float] = {}
    try:
        extracted, timings["extract"] = _timed(
            lambda: _extract_cached(config, cache_dir, source)
        )
        if extracted.status != "ok":
            return _fail_source(
                writer,
                config,
                source,
                doc_id,
                version_id,
                extracted,
                timings,
                extracted.error or extracted.status,
                error_class="extraction",
            )
        segmented, timings["segment"] = _timed(
            lambda: segment_document(
                extracted,
                document_version_id=version_id,
                segmentation_version=config.segmentation_version,
                target_chars=config.target_chars,
                max_chars=config.max_chars,
            )
        )
        draft, timings["build"] = _timed(
            lambda: build_graph(
                collection_id=config.collection_id,
                document_id=doc_id,
                document_version_id=version_id,
                relative_path=source.relative_path,
                source_hash=source.source_hash,
                extracted=extracted,
                segmented=segmented,
                segmentation_version=config.segmentation_version,
                status=STATUS_WRITING,
            )
        )
        memory_check = verify_document(extracted, segmented, draft)
        if not memory_check.ok:
            return _fail_draft(
                writer,
                draft,
                source,
                doc_id,
                version_id,
                extracted,
                timings,
                "; ".join(memory_check.errors),
                chars=len(segmented.canonical_text),
                text_units=len(segmented.units),
                error_class="segmentation",
                segmented=segmented,
                verification=memory_check,
            )
        write_stats, write_seconds = _timed(lambda: writer.write_draft(draft))
        _apply_write_timings(timings, write_stats, write_seconds)
        checked, timings["verify"] = _timed(
            lambda: verify_document(
                extracted,
                segmented,
                draft,
                writer=writer,
                page_count=len(extracted.pages),
            )
        )
        if not checked.ok:
            return _fail_draft(
                writer,
                draft,
                source,
                doc_id,
                version_id,
                extracted,
                timings,
                "; ".join(checked.errors),
                chars=len(segmented.canonical_text),
                text_units=len(segmented.units),
                already_written=True,
                error_class="graph",
                segmented=segmented,
                verification=checked,
                write_stats=write_stats,
            )
        published = dict(draft.document_props)
        published["status"] = STATUS_PUBLISHED
        published["persisted_text_units"] = len(segmented.units)
        _, timings["publish"] = _timed(lambda: writer.publish_document(doc_id, published))
        return _success_outcome(
            source,
            doc_id,
            version_id,
            extracted,
            segmented,
            draft,
            timings,
            write_stats,
            checked,
            config.max_chars,
        )
    except Exception as exc:  # noqa: BLE001 — one file must not stop the batch
        try:
            return _fail_exception(writer, config, source, doc_id, version_id, timings, str(exc))
        except Exception as persist_exc:  # noqa: BLE001 — still report the original file
            return DocumentOutcome(
                relative_path=source.relative_path,
                document_id=doc_id,
                document_version_id=version_id,
                status=STATUS_FAILED_PERMANENT,
                error=f"{exc}; persist failed: {persist_exc}",
                pages=0,
                chars=0,
                text_units=0,
                timings=timings,
            )


def _extract_cached(
    config: IngestConfig,
    cache_dir: Path,
    source: SourceFile,
) -> ExtractedDocument:
    cached = load_extracted(cache_dir, source.source_hash, config.extraction_version)
    if cached is not None:
        return cached
    extracted = extract_file(
        source.path.read_bytes(),
        source.relative_path,
        source.source_hash,
        extraction_version=config.extraction_version,
    )
    store_extracted(cache_dir, extracted)
    return extracted


def _prepare_one(
    config: IngestConfig,
    cache_dir: Path,
    source: SourceFile,
) -> PreparedDocument:
    doc_id = document_id(config.collection_id, source.relative_path)
    version_id = document_version_id(doc_id, source.source_hash)
    timings: dict[str, float] = {}
    extracted, timings["extract"] = _timed(
        lambda: _extract_cached(config, cache_dir, source)
    )
    if extracted.status != "ok":
        return PreparedDocument(
            source=source,
            document_id=doc_id,
            document_version_id=version_id,
            extracted=extracted,
            segmented=None,
            draft=None,
            timings=timings,
            error=extracted.error or extracted.status,
        )
    segmented, timings["segment"] = _timed(
        lambda: segment_document(
            extracted,
            document_version_id=version_id,
            segmentation_version=config.segmentation_version,
            target_chars=config.target_chars,
            max_chars=config.max_chars,
        )
    )
    draft, timings["build"] = _timed(
        lambda: build_graph(
            collection_id=config.collection_id,
            document_id=doc_id,
            document_version_id=version_id,
            relative_path=source.relative_path,
            source_hash=source.source_hash,
            extracted=extracted,
            segmented=segmented,
            segmentation_version=config.segmentation_version,
            status=STATUS_WRITING,
        )
    )
    return PreparedDocument(
        source=source,
        document_id=doc_id,
        document_version_id=version_id,
        extracted=extracted,
        segmented=segmented,
        draft=draft,
        timings=timings,
    )


def _write_prepared_one(
    config: IngestConfig,
    writer: GraphWriter,
    item: PreparedDocument,
) -> DocumentOutcome:
    assert item.draft is not None
    assert item.segmented is not None
    timings: dict[str, float] = {}
    write_stats, write_seconds = _timed(lambda: writer.write_draft(item.draft))
    _apply_write_timings(timings, write_stats, write_seconds)
    checked, timings["verify"] = _timed(
        lambda: verify_document(
            item.extracted,
            item.segmented,
            item.draft,
            writer=writer,
            page_count=len(item.extracted.pages),
        )
    )
    if not checked.ok:
        return _fail_draft(
            writer,
            item.draft,
            item.source,
            item.document_id,
            item.document_version_id,
            item.extracted,
            timings,
            "; ".join(checked.errors),
            chars=len(item.segmented.canonical_text),
            text_units=len(item.segmented.units),
            already_written=True,
            error_class="graph",
            segmented=item.segmented,
            verification=checked,
            write_stats=write_stats,
        )
    published = dict(item.draft.document_props)
    published["status"] = STATUS_PUBLISHED
    published["persisted_text_units"] = len(item.segmented.units)
    _, timings["publish"] = _timed(
        lambda: writer.publish_document(item.document_id, published)
    )
    return _success_outcome(
        item.source,
        item.document_id,
        item.document_version_id,
        item.extracted,
        item.segmented,
        item.draft,
        timings,
        write_stats,
        checked,
        config.max_chars,
    )


def _fail_prepared(
    writer: GraphWriter,
    config: IngestConfig,
    item: PreparedDocument,
) -> DocumentOutcome:
    return _fail_source(
        writer,
        config,
        item.source,
        item.document_id,
        item.document_version_id,
        item.extracted,
        {},
        item.error or "prepare failed",
        error_class="extraction",
    )


def _fail_source(
    writer: GraphWriter,
    config: IngestConfig,
    source: SourceFile,
    doc_id: str,
    version_id: str,
    extracted: ExtractedDocument,
    timings: dict[str, float],
    error: str,
    *,
    error_class: str = "extraction",
) -> DocumentOutcome:
    draft = _failed_document_draft(config, source, doc_id, version_id, extracted, error)
    writer.write_draft(draft)
    writer.publish_document(doc_id, dict(draft.document_props))
    return DocumentOutcome(
        relative_path=source.relative_path,
        document_id=doc_id,
        document_version_id=version_id,
        status=STATUS_FAILED_PERMANENT,
        error=error,
        pages=len(extracted.pages),
        chars=0,
        text_units=0,
        timings=timings,
        error_class=error_class,
        exclusions=len(extracted.exclusions()),
        exclusion_reasons=[
            block.exclude_reason or "unspecified" for block in extracted.exclusions()
        ],
    )


def _fail_draft(
    writer: GraphWriter,
    draft: GraphDraft,
    source: SourceFile,
    doc_id: str,
    version_id: str,
    extracted: ExtractedDocument,
    timings: dict[str, float],
    error: str,
    *,
    chars: int,
    text_units: int,
    already_written: bool = False,
    error_class: str = "segmentation",
    segmented: SegmentedDocument | None = None,
    verification=None,
    write_stats: WriteStats | None = None,
) -> DocumentOutcome:
    props = dict(draft.document_props)
    props["status"] = STATUS_FAILED_PERMANENT
    props["error"] = error
    failed = GraphDraft(
        nodes=[
            node
            for node in draft.nodes
            if node.labels[0] in {"Collection", "Document"}
        ],
        edges=[
            edge
            for edge in draft.edges
            if edge.label == "CONTAINS" and edge.from_label == "Collection"
        ],
        document_key=doc_id,
        document_props=props,
    )
    if already_written:
        writer.publish_document(doc_id, props)
    else:
        writer.write_draft(failed)
        writer.publish_document(doc_id, props)
    outcome = DocumentOutcome(
        relative_path=source.relative_path,
        document_id=doc_id,
        document_version_id=version_id,
        status=STATUS_FAILED_PERMANENT,
        error=error,
        pages=len(extracted.pages),
        chars=chars,
        text_units=text_units,
        timings=timings,
        error_class=error_class,
    )
    if segmented is not None and verification is not None:
        _attach_structure(outcome, extracted, segmented, draft, verification, 2400)
    if write_stats is not None:
        outcome.write_batches = _batch_payloads(write_stats)
        outcome.nodes = write_stats.nodes
        outcome.edges = write_stats.edges
    return outcome


def _fail_exception(
    writer: GraphWriter,
    config: IngestConfig,
    source: SourceFile,
    doc_id: str,
    version_id: str,
    timings: dict[str, float],
    error: str,
) -> DocumentOutcome:
    extracted = ExtractedDocument(
        relative_path=source.relative_path,
        mime_type="application/octet-stream",
        source_hash=source.source_hash,
        extraction_version=config.extraction_version,
        status="failed",
        error=error,
    )
    return _fail_source(
        writer,
        config,
        source,
        doc_id,
        version_id,
        extracted,
        timings,
        error,
        error_class="unknown",
    )


def _success_outcome(
    source: SourceFile,
    doc_id: str,
    version_id: str,
    extracted: ExtractedDocument,
    segmented: SegmentedDocument,
    draft: GraphDraft,
    timings: dict[str, float],
    write_stats: WriteStats,
    verification,
    max_chars: int,
) -> DocumentOutcome:
    outcome = DocumentOutcome(
        relative_path=source.relative_path,
        document_id=doc_id,
        document_version_id=version_id,
        status=STATUS_PUBLISHED,
        error=None,
        pages=len(extracted.pages),
        chars=len(segmented.canonical_text),
        text_units=len(segmented.units),
        timings=timings,
        write_batches=_batch_payloads(write_stats),
        nodes=write_stats.nodes,
        edges=write_stats.edges,
    )
    _attach_structure(outcome, extracted, segmented, draft, verification, max_chars)
    return outcome


def _attach_structure(
    outcome: DocumentOutcome,
    extracted: ExtractedDocument,
    segmented: SegmentedDocument,
    draft: GraphDraft,
    verification,
    max_chars: int,
) -> None:
    stats = collect_structure_stats(
        extracted,
        segmented,
        draft,
        verification,
        max_chars=max_chars,
    )
    outcome.structures = stats.structures
    outcome.clauses = stats.clauses
    outcome.split_structures = stats.split_structures
    outcome.split_text_units = stats.split_text_units
    outcome.oversized_units = stats.oversized_units
    outcome.exclusions = stats.exclusions
    outcome.exclusion_reasons = stats.exclusion_reasons
    outcome.text_unit_sizes = stats.text_unit_sizes
    outcome.coverage = stats.coverage
    outcome.reconstructed = stats.reconstructed
    if not outcome.nodes:
        outcome.nodes = stats.nodes
    if not outcome.edges:
        outcome.edges = stats.edges


def _apply_write_timings(
    timings: dict[str, float],
    write_stats: WriteStats,
    write_seconds: float,
) -> None:
    timings["write"] = write_seconds
    timings["write_nodes"] = write_stats.node_seconds
    timings["write_edges"] = write_stats.edge_seconds


def _batch_payloads(write_stats: WriteStats) -> list[dict[str, object]]:
    return [
        {"kind": batch.kind, "count": batch.count, "seconds": batch.seconds}
        for batch in write_stats.batches
    ]


def _failed_document_draft(
    config: IngestConfig,
    source: SourceFile,
    doc_id: str,
    version_id: str,
    extracted: ExtractedDocument,
    error: str,
) -> GraphDraft:
    empty = SegmentedDocument(canonical_text="")
    draft = build_graph(
        collection_id=config.collection_id,
        document_id=doc_id,
        document_version_id=version_id,
        relative_path=source.relative_path,
        source_hash=source.source_hash,
        extracted=extracted,
        segmented=empty,
        segmentation_version=config.segmentation_version,
        status=STATUS_FAILED_PERMANENT,
        extra_document_props={"error": error},
    )
    return draft


def _timed(work):
    started = time.perf_counter()
    result = work()
    return result, time.perf_counter() - started


def _peak_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(usage)
    return int(usage) * 1024


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
