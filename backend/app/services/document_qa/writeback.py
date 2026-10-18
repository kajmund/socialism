"""Persist Q&A after the user already has the answer. Failure must not block."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.services.document_qa.access import STORE_FAILURES, Viewer
from app.services.document_qa.store import persist
from app.services.document_qa.tenants import TenantCatalogs
from app.services.document_qa.types import FlushResult, QaWrite, UserAnswer
from app.services.overgraph.catalogs import Catalog

PersistFn = Callable[[Catalog, Viewer, QaWrite], object]


def remember_answer(write: QaWrite) -> UserAnswer:
    return UserAnswer(text=write.answer_text, status=write.status, persisted=False)


def persist_after_answer(
    catalog: Catalog,
    viewer: Viewer,
    write: QaWrite,
    *,
    persist_fn: PersistFn = persist,
) -> UserAnswer:
    answer = remember_answer(write)
    try:
        persist_fn(catalog, viewer, write)
    except STORE_FAILURES:
        return answer
    return UserAnswer(text=write.answer_text, status=write.status, persisted=True)


@dataclass
class PendingQa:
    viewer: Viewer
    write: QaWrite


class QaOutbox:
    """In-process writeback. A purge drops pending rows so they cannot recreate."""

    def __init__(self, catalogs: TenantCatalogs, *, persist_fn: PersistFn = persist) -> None:
        self._catalogs = catalogs
        self._persist = persist_fn
        self._pending: list[PendingQa] = []
        self._purged: set[tuple[int, str]] = set()

    def enqueue(self, viewer: Viewer, write: QaWrite) -> UserAnswer:
        key = (viewer.customer_id, write.document_id)
        if key in self._purged:
            return remember_answer(write)
        self._pending.append(PendingQa(viewer, write))
        return remember_answer(write)

    def drop_document(self, customer_id: int, document_id: str) -> None:
        self._purged.add((customer_id, document_id))
        self._pending = [
            item
            for item in self._pending
            if (item.viewer.customer_id, item.write.document_id) != (customer_id, document_id)
        ]

    def flush(self) -> list[FlushResult]:
        results = [_flush_one(self, item) for item in self._pending]
        self._pending = []
        return results


def _flush_one(outbox: QaOutbox, item: PendingQa) -> FlushResult:
    key = (item.viewer.customer_id, item.write.document_id)
    if key in outbox._purged:
        return FlushResult(ok=False, reason="purged")
    try:
        outbox._persist(outbox._catalogs.open_for(item.viewer.customer_id), item.viewer, item.write)
    except STORE_FAILURES as exc:
        return FlushResult(ok=False, reason=str(exc) or exc.__class__.__name__)
    return FlushResult(ok=True)
