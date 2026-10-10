"""JSON timing and quality report for a sequential ingest baseline."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.config import IngestConfig
from overgraph_ingest.graph.schema import STATUS_PUBLISHED
from overgraph_ingest.metrics import (
    count_reasons,
    environment_metadata,
    percentile,
    size_buckets,
    summarize_values,
)
from overgraph_ingest.pipeline import RunReport


def report_payload(config: IngestConfig, report: RunReport) -> dict[str, object]:
    published = [item for item in report.outcomes if item.status == STATUS_PUBLISHED]
    failed = [item for item in report.outcomes if item.status != STATUS_PUBLISHED]
    pages = sum(item.pages for item in report.outcomes)
    chars = sum(item.chars for item in published)
    units = sum(item.text_units for item in published)
    elapsed = max(report.total_seconds, 1e-9)
    write_seconds = report.stage_seconds.get("write", 0.0)
    finalize = report.finalize_seconds or {}
    persist_seconds = write_seconds + finalize.get("end_ingest", 0.0) + finalize.get("sync", 0.0)
    sizes = [size for item in published for size in item.text_unit_sizes]
    exclusions = [reason for item in report.outcomes for reason in item.exclusion_reasons]
    node_upserts = report.node_upserts
    edge_upserts = report.edge_upserts
    return {
        "collection_id": report.collection_id,
        "input": str(config.input_dir) if config.input_dir else None,
        "db": str(config.db_path),
        "environment": environment_metadata(),
        "segmentation_version": config.segmentation_version,
        "write_batch_size": config.write_batch_size,
        "document_count": len(report.outcomes),
        "published": len(published),
        "failed": len(failed),
        "pages": pages,
        "characters": chars,
        "text_units": units,
        "structures": sum(item.structures for item in published),
        "clauses": sum(item.clauses for item in published),
        "nodes": node_upserts,
        "edges": edge_upserts,
        "split_structures": sum(item.split_structures for item in published),
        "split_text_units": sum(item.split_text_units for item in published),
        "oversized_text_units": sum(item.oversized_units for item in published),
        "exclusions": sum(item.exclusions for item in report.outcomes),
        "exclusion_reasons": count_reasons(exclusions),
        "text_coverage_mean": (
            sum(item.coverage for item in published) / len(published) if published else 0.0
        ),
        "reconstructed_documents": sum(1 for item in published if item.reconstructed),
        "total_seconds": report.total_seconds,
        "publish_ready_seconds": report.publish_ready_seconds,
        "stage_seconds": report.stage_seconds,
        "finalize_seconds": finalize,
        "persist_seconds": persist_seconds,
        "documents_per_second": len(report.outcomes) / elapsed,
        "pages_per_second": pages / elapsed,
        "chars_per_million_seconds": (chars / 1_000_000) / elapsed if chars else 0.0,
        "seconds_per_page": report.total_seconds / pages if pages else None,
        "seconds_per_million_chars": report.total_seconds / (chars / 1_000_000) if chars else None,
        "text_units_per_second": units / elapsed,
        "nodes_per_second": node_upserts / max(write_seconds, 1e-9),
        "edges_per_second": edge_upserts / max(report.stage_seconds.get("write_edges", 0.0), 1e-9),
        "nodes_per_second_including_finalize": node_upserts / max(persist_seconds, 1e-9),
        "edges_per_second_including_finalize": edge_upserts / max(
            report.stage_seconds.get("write_edges", 0.0) + finalize.get("end_ingest", 0.0) + finalize.get("sync", 0.0),
            1e-9,
        ),
        "edges_per_text_unit": edge_upserts / units if units else 0.0,
        "text_units_per_document": summarize_values([item.text_units for item in published]),
        "text_units_per_clause": (
            units / sum(item.clauses for item in published)
            if sum(item.clauses for item in published)
            else None
        ),
        "text_unit_size": summarize_values(sizes),
        "text_unit_size_buckets": size_buckets(sizes),
        "write_batches": _summarize_batches(report.write_batches),
        "peak_rss_bytes": report.peak_rss_bytes,
        "peak_rss_mb": report.peak_rss_bytes / (1024 * 1024),
        "disk_bytes": report.disk_bytes,
        "disk_mb": report.disk_bytes / (1024 * 1024),
        "error_classes": count_reasons(
            [item.error_class for item in failed if item.error_class]
        ),
        "headline": _headline(report, pages, chars, units, node_upserts, edge_upserts, published),
        "documents": [
            {
                "relative_path": item.relative_path,
                "status": item.status,
                "error": item.error,
                "error_class": item.error_class,
                "pages": item.pages,
                "characters": item.chars,
                "text_units": item.text_units,
                "structures": item.structures,
                "clauses": item.clauses,
                "nodes": item.nodes,
                "edges": item.edges,
                "coverage": item.coverage,
                "reconstructed": item.reconstructed,
                "seconds": item.timings,
                "publish_seconds": _document_ready(item.timings),
            }
            for item in report.outcomes
        ],
    }


def write_report(config: IngestConfig, report: RunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_payload(config, report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _document_ready(timings: dict[str, float]) -> float:
    return sum(
        timings.get(name, 0.0)
        for name in (
            "extract",
            "segment",
            "build",
            "write",
            "verify",
            "publish",
        )
    )


def _summarize_batches(batches: list[dict[str, object]]) -> dict[str, object]:
    by_kind: dict[str, list[dict[str, object]]] = {"nodes": [], "edges": []}
    for batch in batches:
        kind = str(batch.get("kind") or "")
        by_kind.setdefault(kind, []).append(batch)
    summary: dict[str, object] = {}
    for kind, items in by_kind.items():
        counts = [int(item["count"]) for item in items]
        seconds = [float(item["seconds"]) for item in items]
        summary[kind] = {
            "batches": len(items),
            "count": summarize_values(counts),
            "seconds": summarize_values(seconds),
            "p50_seconds": percentile(seconds, 50),
            "p95_seconds": percentile(seconds, 95),
        }
    return summary


def _headline(
    report: RunReport,
    pages: int,
    chars: int,
    units: int,
    nodes: int,
    edges: int,
    published: list,
) -> dict[str, object]:
    stages = report.stage_seconds
    finalize = report.finalize_seconds or {}
    return {
        "documents": f"{len(published)}/{len(report.outcomes)}",
        "pages": pages,
        "characters": chars,
        "text_units": units,
        "nodes": nodes,
        "edges": edges,
        "extraction_seconds": stages.get("extract", 0.0),
        "segmentation_seconds": stages.get("segment", 0.0),
        "graph_construction_seconds": stages.get("build", 0.0),
        "overgraph_batch_write_seconds": stages.get("write", 0.0),
        "overgraph_finalize_seconds": finalize.get("end_ingest", 0.0) + finalize.get("sync", 0.0),
        "end_ingest_seconds": finalize.get("end_ingest", 0.0),
        "sync_seconds": finalize.get("sync", 0.0),
        "verification_seconds": stages.get("verify", 0.0),
        "total_seconds": report.total_seconds,
        "peak_rss_mb": report.peak_rss_bytes / (1024 * 1024),
        "disk_mb": report.disk_bytes / (1024 * 1024),
        "text_coverage": (
            sum(item.coverage for item in published) / len(published) if published else 0.0
        ),
    }
