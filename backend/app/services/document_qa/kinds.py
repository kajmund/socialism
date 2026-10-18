"""Outbox job kinds. Legal writes stay on the shared catalog until migrated."""

LEGAL_GRAPH_WRITE = "legal_graph_write"
DOCUMENT_QA_WRITE = "document_qa_write"
DOCUMENT_CATALOG_WRITE = "document_catalog_write"


def work_kind(payload: dict[str, object]) -> str:
    kind = payload.get("kind")
    if kind in {DOCUMENT_QA_WRITE, DOCUMENT_CATALOG_WRITE}:
        return str(kind)
    return LEGAL_GRAPH_WRITE
