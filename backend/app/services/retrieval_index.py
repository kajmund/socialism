"""Process-owned Tantivy index used by research retrieval.

The index is derived from OverGraph and may lag. Research must never silently fall back
to dense-only, so a missing or lagging index raises a visible error; ``index_cli`` rebuilds
or reconciles it from the graph.
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.config import settings
from app.services.overgraph.catalogs import catalog_root, require_knowledge
from app.services.overgraph.hybrid_retrieval import FactIndexStaleError, fact_index_lag
from app.services.tantivy_index import INDEX_VERSION, TextUnitIndex, read_index_version


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


def require_current_index() -> TextUnitIndex:
    """The open index, but only if it reflects the current graph revision."""
    index = _index
    if index is None:
        raise RetrievalIndexUnavailableError(
            "lexical index is not open; start it from the built index or rebuild it"
        )
    pending = fact_index_lag(require_knowledge(), _index_dir or index_directory())
    if pending:
        raise FactIndexStaleError(
            f"lexical index is {pending} change(s) behind the graph; run "
            "python -m app.services.knowledge.index_cli reconcile"
        )
    return index
