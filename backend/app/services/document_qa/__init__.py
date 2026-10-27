"""Document Q&A contracts plus test/offline direct helpers.

Request paths use the Owner-backed modules (``owner_qa``, ``owner_ingest``,
``owner_find``, ``owner_qa_retrieve``). The direct helpers re-exported here are
kept for unit tests and offline tooling and are loaded lazily so serving a
request never imports a local tenant catalog writer.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "QaPermissionError": "access",
    "QaStoreError": "access",
    "Viewer": "access",
    "AnalysisContract": "types",
    "AnswerPostWrite": "types",
    "QaWrite": "types",
    "SourceCite": "types",
    "archive_document": "lifecycle",
    "purge_document": "lifecycle",
    "enqueue_document_qa": "outbox",
    "cache_decision": "retrieve",
    "exact_reuse": "retrieve",
    "semantic_candidates": "retrieve",
    "review_answer": "review",
    "review_history": "review",
    "persist": "store",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value
