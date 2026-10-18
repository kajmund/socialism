"""Graph labels for document-find category index on tenant OverGraph."""

from app.services.document_qa.labels import CANONICAL_DOCUMENT, HAS_VERSION
from app.services.overgraph.labels import CONTAINS, DOCUMENT_VERSION, TEXT_UNIT

DOCUMENT_CATEGORY = "DocumentCategory"
IN_CATEGORY = "IN_CATEGORY"

__all__ = [
    "CANONICAL_DOCUMENT",
    "CONTAINS",
    "DOCUMENT_CATEGORY",
    "DOCUMENT_VERSION",
    "HAS_VERSION",
    "IN_CATEGORY",
    "TEXT_UNIT",
]
