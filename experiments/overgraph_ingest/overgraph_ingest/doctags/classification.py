"""Reuse frozen document-type B. Do not re-run classification Jev."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.doctags.gold import DOCUMENTS
from overgraph_ingest.retrieval.conclusions import DOCTYPE_RUN_PATH


def load_frozen_classifications(
    path: Path | None = None,
    *,
    documents: tuple[str, ...] = DOCUMENTS,
) -> dict[str, dict[str, object]]:
    payload = json.loads((path or DOCTYPE_RUN_PATH).read_text(encoding="utf-8"))
    rows = payload["scored"]["B"]
    selected = {
        str(row["relative_path"]): row
        for row in rows
        if str(row["relative_path"]) in documents
    }
    missing = [path for path in documents if path not in selected]
    if missing:
        raise ValueError(f"frozen doctype B missing paths: {missing}")
    return selected


def classification_record(row: dict[str, object]) -> dict[str, object]:
    distribution = row.get("distribution")
    if not isinstance(distribution, dict):
        classification = row.get("classification")
        if isinstance(classification, dict):
            distribution = classification.get("distribution")
    return {
        "predicted_type": str(row["document_type"]),
        "confidence": row.get("score"),
        "probabilities": distribution if isinstance(distribution, dict) else {},
        "model": str(row.get("model") or ""),
        "taxonomy_version": str(row.get("taxonomy_version") or ""),
        "document_id": str(row["document_id"]),
        "relative_path": str(row["relative_path"]),
    }
