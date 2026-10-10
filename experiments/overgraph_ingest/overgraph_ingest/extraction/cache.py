"""Atomic JSON cache of extracted documents, keyed by source hash + version."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.extraction.model import (
    ExtractedDocument,
    document_from_dict,
    document_to_dict,
)


def cache_path(cache_dir: Path, source_hash: str, extraction_version: str) -> Path:
    return cache_dir / f"{source_hash}.{extraction_version}.json"


def load_extracted(
    cache_dir: Path,
    source_hash: str,
    extraction_version: str,
) -> ExtractedDocument | None:
    path = cache_path(cache_dir, source_hash, extraction_version)
    if not path.is_file():
        return None
    return document_from_dict(json.loads(path.read_text(encoding="utf-8")))


def store_extracted(cache_dir: Path, document: ExtractedDocument) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(cache_dir, document.source_hash, document.extraction_version)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(document_to_dict(document), ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)
    return path
