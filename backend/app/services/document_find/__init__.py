"""Document-centered find on tenant OverGraph. Prove via integration tests first.

Exports are lazy so importing a submodule (labels/taxonomy) does not pull the
strategy layer and its graph-write imports. That keeps owner repositories free
of the historical `document_find -> strategies -> graph_v2.types -> knowledge`
import cycle.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "classify_document": "classify",
    "classify_and_index": "strategies",
    "extend_set": "strategies",
    "filter_to_set": "strategies",
    "find_by_category": "strategies",
    "find_by_hybrid": "strategies",
    "find_by_shared_party": "strategies",
    "find_category_then_hybrid": "strategies",
    "find_within_documents": "strategies",
    "FindRequest": "request",
    "empty_scope_result": "request",
    "needs_embedding": "request",
    "normalize_find_mode": "request",
    "presentation_slice": "request",
    "run_find": "tool",
    "suggested_title": "request",
    "FindResult": "types",
    "OpCounters": "types",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value
