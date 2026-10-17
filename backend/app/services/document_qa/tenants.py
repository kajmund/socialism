"""One OverGraph file database per tenant. Path comes from verified customer_id."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from overgraph import OverGraphError

from app.services.document_qa.access import require_customer_id
from app.services.document_qa.tenant_lock import TenantLock
from app.services.overgraph.catalogs import Catalog, open_catalog

CLOSE_ERRORS = (OverGraphError, OSError, RuntimeError)


@dataclass
class TenantTimings:
    lock_wait_ms: float = 0.0
    open_ms: float = 0.0
    close_ms: float = 0.0


def tenant_catalog_path(root: Path, customer_id: int) -> Path:
    customer_id = require_customer_id(customer_id)
    return Path(root) / "tenants" / str(customer_id) / "knowledge"


def tenant_lock_path(root: Path, customer_id: int) -> Path:
    return tenant_catalog_path(root, customer_id).parent / "tenant.lock"


class TenantCatalogs:
    """Only legal opener for a tenant OverGraph file.

    The client never chooses the path. `flock` is held from before
    OverGraph.open until after close. Ingest, tags, Q&A, and expert
    tools must use this registry. A second open path would skip the
    advisory lock and can corrupt the file.
    """

    def __init__(self, root: Path, *, dimension: int, lock_timeout: float = 30.0) -> None:
        if dimension < 1:
            raise ValueError("tenant catalog dimension must be >= 1")
        if lock_timeout <= 0:
            raise ValueError("lock_timeout must be > 0")
        self.root = Path(root)
        self.dimension = dimension
        self.lock_timeout = lock_timeout
        self.timings = TenantTimings()
        self._lock = threading.Lock()
        self._open: dict[int, Catalog] = {}
        self._file_locks: dict[int, TenantLock] = {}

    def open_for(self, customer_id: int) -> Catalog:
        customer_id = require_customer_id(customer_id)
        with self._lock:
            existing = self._open.get(customer_id)
            if existing is not None:
                return existing
            catalog = self._open_locked(customer_id)
            self._open[customer_id] = catalog
            return catalog

    def close(self) -> None:
        with self._lock:
            owned = [
                (self._open.pop(customer_id), self._file_locks.pop(customer_id))
                for customer_id in list(self._open)
            ]
        error: Exception | None = None
        started = time.perf_counter()
        for catalog, file_lock in owned:
            error = _close_one(catalog, file_lock, error)
        self.timings.close_ms = (time.perf_counter() - started) * 1000
        if error is not None:
            raise error

    def _open_locked(self, customer_id: int) -> Catalog:
        file_lock = TenantLock(tenant_lock_path(self.root, customer_id))
        wait_ms = file_lock.acquire(timeout=self.lock_timeout)
        started = time.perf_counter()
        try:
            catalog = open_catalog(
                tenant_catalog_path(self.root, customer_id),
                kind="knowledge",
                dimension=self.dimension,
            )
        except CLOSE_ERRORS:
            file_lock.release()
            raise
        self._file_locks[customer_id] = file_lock
        self.timings = TenantTimings(
            lock_wait_ms=wait_ms,
            open_ms=(time.perf_counter() - started) * 1000,
        )
        return catalog


def _close_one(catalog: Catalog, file_lock: TenantLock, error: Exception | None) -> Exception | None:
    try:
        catalog.close()
    except CLOSE_ERRORS as exc:
        error = error or exc
    file_lock.release()
    return error


_registry: TenantCatalogs | None = None


def set_tenant_catalogs(catalogs: TenantCatalogs | None) -> None:
    global _registry
    if _registry is not None and catalogs is not _registry:
        _registry.close()
    _registry = catalogs


def get_tenant_catalogs() -> TenantCatalogs | None:
    return _registry


def require_tenant_catalogs() -> TenantCatalogs:
    if _registry is None:
        raise RuntimeError("tenant OverGraph owner is not open")
    return _registry
