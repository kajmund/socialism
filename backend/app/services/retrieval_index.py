"""Process-owned Tantivy index used by research retrieval.

The index is derived from OverGraph and may lag. The lifespan opens, builds, or reconciles
it from the graph; research must never silently fall back to dense-only.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.config import settings
from app.services.overgraph.catalogs import catalog_root, require_knowledge
from app.services.overgraph.hybrid_retrieval import FactIndexStaleError, fact_index_lag
from app.services.tantivy_index import (
    INDEX_VERSION,
    TextUnitIndex,
    build_from_overgraph,
    read_index_version,
    read_watermark,
    reconcile,
    write_watermark,
)

logger = logging.getLogger(__name__)


class RetrievalIndexUnavailableError(RuntimeError):
    """The derived lexical index is not open or not built."""


_lock = threading.Lock()
_index: TextUnitIndex | None = None
_index_dir: Path | None = None


def index_directory() -> Path:
    return Path(catalog_root(settings.overgraph_dir)) / "tantivy"


def set_index(index: TextUnitIndex | None, directory: Path | None = None) -> None:
    global _index, _index_dir
    with _lock:
        _index = index
        _index_dir = Path(directory) if directory is not None else index_directory()


def get_index() -> TextUnitIndex | None:
    return _index


def open_index(directory: Path | None = None) -> TextUnitIndex:
    target = Path(directory) if directory is not None else index_directory()
    version = read_index_version(target)
    if version != INDEX_VERSION:
        raise RetrievalIndexUnavailableError(
            f"lexical index at {target} was built with version {version or 'unknown'!r}, "
            f"expected {INDEX_VERSION!r}; rebuild the index from OverGraph"
        )
    try:
        return TextUnitIndex.open(target / "current")
    except Exception as exc:  # tantivy raises its own error type
        raise RetrievalIndexUnavailableError(
            f"no built lexical index at {target}; rebuild the index from OverGraph"
        ) from exc


def _reconcile_locked(catalog, index: TextUnitIndex, target: Path) -> None:
    new_watermark = reconcile(
        catalog, index, watermark_ms=read_watermark(target),
    )
    write_watermark(target, new_watermark)


def _ensure_current_locked(catalog, target: Path) -> TextUnitIndex | None:
    index = _index
    if index is None:
        try:
            index = open_index(target)
        except RetrievalIndexUnavailableError:
            try:
                index = build_from_overgraph(catalog, target)
            except ValueError as exc:
                if "empty graph" in str(exc):
                    logger.info(
                        "lexical index deferred: graph is empty at %s", target,
                    )
                    return None
                raise
        logger.info("lexical index opened/built at %s", target)
    _reconcile_locked(catalog, index, target)
    return index


def ensure_current() -> TextUnitIndex | None:
    """Open/build/reconcile the process index from OverGraph.

    Returns None when the graph is empty and there is nothing to index yet.
    A non-empty graph that cannot be indexed raises instead of being hidden.
    """
    target = _index_dir or index_directory()
    catalog = require_knowledge()
    with _lock:
        index = _ensure_current_locked(catalog, target)
        if index is not None:
            _set_index_locked(index, target)
        return index


def _set_index_locked(index: TextUnitIndex, directory: Path) -> None:
    global _index, _index_dir
    _index = index
    _index_dir = directory


def require_current_index() -> TextUnitIndex:
    """The open index, reconciled to the current graph revision when needed."""
    target = _index_dir or index_directory()
    catalog = require_knowledge()
    with _lock:
        index = _index
        if index is None:
            index = _ensure_current_locked(catalog, target)
        else:
            pending = fact_index_lag(catalog, target)
            if pending:
                _reconcile_locked(catalog, index, target)
        if index is None:
            raise RetrievalIndexUnavailableError(
                "lexical index is unavailable and the graph is empty; ingest "
                "documents before running research"
            )
        _set_index_locked(index, target)
        pending = fact_index_lag(catalog, target)
        if pending:
            raise FactIndexStaleError(
                f"lexical index is {pending} change(s) behind the graph; "
                "reconcile it from OverGraph"
            )
        return index
