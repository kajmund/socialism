"""Freeze a sequential ingest report as the official phase-1 performance baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from overgraph_ingest.graph.schema import STATUS_PUBLISHED

BASELINE_ID = "phase1-sequential-100-docx"
BASELINE_LABEL = (
    "Official sequential phase-1 baseline: 100 real Swedish DOCX contracts, "
    "single writer, no parallel extraction"
)
OFFICIAL_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{BASELINE_ID}.json"
)

_KEEP = (
    "collection_id",
    "environment",
    "segmentation_version",
    "write_batch_size",
    "document_count",
    "published",
    "failed",
    "characters",
    "text_units",
    "structures",
    "clauses",
    "nodes",
    "edges",
    "text_coverage_mean",
    "reconstructed_documents",
    "total_seconds",
    "publish_ready_seconds",
    "stage_seconds",
    "finalize_seconds",
    "persist_seconds",
    "documents_per_second",
    "text_unit_size",
    "text_unit_size_buckets",
    "peak_rss_mb",
    "disk_mb",
    "headline",
)


def freeze_baseline(payload: dict[str, Any]) -> dict[str, Any]:
    frozen = {key: payload[key] for key in _KEEP if key in payload}
    documents = list(payload.get("documents") or [])
    frozen["id"] = BASELINE_ID
    frozen["label"] = BASELINE_LABEL
    frozen["zero_clause_documents"] = [
        str(item.get("relative_path") or "")
        for item in documents
        if item.get("status") == STATUS_PUBLISHED and int(item.get("clauses") or 0) == 0
    ]
    frozen["documents"] = [
        {
            "relative_path": item.get("relative_path"),
            "status": item.get("status"),
            "characters": item.get("characters"),
            "text_units": item.get("text_units"),
            "structures": item.get("structures"),
            "clauses": item.get("clauses"),
            "coverage": item.get("coverage"),
            "reconstructed": item.get("reconstructed"),
        }
        for item in documents
    ]
    return frozen


def write_official_baseline(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = path or OFFICIAL_BASELINE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(freeze_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_official_baseline(path: Path | None = None) -> dict[str, Any]:
    target = path or OFFICIAL_BASELINE_PATH
    return json.loads(target.read_text(encoding="utf-8"))
