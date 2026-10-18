"""Document-centered find on tenant OverGraph. Prove via integration tests first."""

from app.services.document_find.classify import classify_document
from app.services.document_find.strategies import (
    classify_and_index,
    extend_set,
    filter_to_set,
    find_by_category,
    find_by_hybrid,
    find_by_shared_party,
    find_category_then_hybrid,
    find_within_documents,
)
from app.services.document_find.tool import (
    needs_embedding,
    normalize_find_mode,
    presentation_slice,
    run_find,
    suggested_title,
)
from app.services.document_find.types import FindResult, OpCounters

__all__ = [
    "FindResult",
    "OpCounters",
    "classify_and_index",
    "classify_document",
    "extend_set",
    "filter_to_set",
    "find_by_category",
    "find_by_hybrid",
    "find_by_shared_party",
    "find_category_then_hybrid",
    "find_within_documents",
    "needs_embedding",
    "normalize_find_mode",
    "presentation_slice",
    "run_find",
    "suggested_title",
]
