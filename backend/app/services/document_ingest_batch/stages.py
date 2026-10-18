"""Ingest stages. Searchable is indexing complete, not classification."""

WAITING = "waiting"
UPLOADING = "uploading"
EXTRACTING = "extracting"
INDEXING = "indexing"
CLASSIFYING = "classifying"
ENRICHING = "enriching"
READY = "ready"
SKIPPED = "skipped"
FAILED = "failed"

PENDING = "pending"
PROCESSING = "processing"
COMPLETED = "completed"

SEARCHABLE_STAGES = frozenset({CLASSIFYING, ENRICHING, READY})
TERMINAL_STATUSES = frozenset({READY, FAILED, SKIPPED})
FAILED_KNOWLEDGE = frozenset({"failed", "empty", "unsupported", "needs_ocr", "partial"})


def ingest_percent(*, unit_done: int, unit_total: int, searchable: bool) -> int:
    if searchable:
        return 100
    if unit_total <= 0 or unit_done <= 0:
        return 0
    return min(99, (unit_done * 100) // unit_total)


def upload_percent(*, stored: bool) -> int:
    return 100 if stored else 0
