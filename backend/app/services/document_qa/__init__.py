"""Document Q&A in a per-tenant OverGraph. Retrieval is not wired to chat."""

from app.services.document_qa.access import QaPermissionError, QaStoreError, Viewer
from app.services.document_qa.lifecycle import archive_document, purge_document
from app.services.document_qa.outbox import enqueue_document_qa
from app.services.document_qa.retrieve import cache_decision, exact_reuse, semantic_candidates
from app.services.document_qa.review import review_answer, review_history
from app.services.document_qa.store import persist
from app.services.document_qa.tenants import TenantCatalogs
from app.services.document_qa.types import AnalysisContract, AnswerPostWrite, QaWrite, SourceCite
from app.services.document_qa.writeback import QaOutbox, persist_after_answer

__all__ = [
    "AnalysisContract",
    "AnswerPostWrite",
    "QaOutbox",
    "QaPermissionError",
    "QaStoreError",
    "QaWrite",
    "SourceCite",
    "TenantCatalogs",
    "Viewer",
    "archive_document",
    "cache_decision",
    "enqueue_document_qa",
    "exact_reuse",
    "persist",
    "persist_after_answer",
    "purge_document",
    "review_answer",
    "review_history",
    "semantic_candidates",
]
