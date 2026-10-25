"""Isolated tests for the opt-in read/write Catalog lock experiment."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
from pathlib import Path

import pytest

from overgraph import OverGraphError

from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.owner_locks import enable_read_write_lock
from app.services.overgraph.labels import FACT, scope_label


def _seed(catalog) -> None:
    for index in range(100):
        catalog.upsert_node(
            [FACT, scope_label("customer:1")], f"lock-{index}",
            props={"scope_key": "customer:1", "status": "active"},
        )


def test_read_write_lock_allows_concurrent_reads_and_exclusive_writes():
    root = Path(tempfile.mkdtemp(prefix="catalog-rw-"))
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=4)
    enable_read_write_lock(catalog)
    _seed(catalog)
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                catalog.get_by_key(FACT, "lock-0")
                catalog.count_nodes_by_labels([FACT])
        except (OverGraphError, RuntimeError, ValueError, TypeError) as exc:
            errors.append(exc)

    def writer() -> None:
        try:
            for index in range(200):
                catalog.upsert_node(
                    [FACT, scope_label("customer:1")], f"writer-{index}",
                    props={"scope_key": "customer:1", "status": "active"},
                )
        except (OverGraphError, RuntimeError, ValueError, TypeError) as exc:
            errors.append(exc)
        finally:
            stop.set()

    readers = [threading.Thread(target=reader) for _ in range(4)]
    write_thread = threading.Thread(target=writer)
    for thread in readers:
        thread.start()
    write_thread.start()
    write_thread.join(timeout=10)
    for thread in readers:
        thread.join(timeout=10)
    try:
        assert not write_thread.is_alive()
        assert all(not thread.is_alive() for thread in readers)
        assert errors == []
        assert catalog.count_nodes_by_labels([FACT]) == 300
    finally:
        catalog.close()


def test_close_waits_for_an_inflight_read_before_closing_the_handle():
    root = Path(tempfile.mkdtemp(prefix="catalog-rw-close-"))
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=4)
    enable_read_write_lock(catalog)
    _seed(catalog)
    started = threading.Event()
    finished = threading.Event()

    errors: list[BaseException] = []

    def read() -> None:
        try:
            def slow_read(db):
                started.set()
                time.sleep(0.2)
                finished.set()
                return db.get_node_by_key(FACT, "lock-0")

            catalog.read(slow_read)
        except (OverGraphError, RuntimeError, ValueError, TypeError) as exc:
            errors.append(exc)

    thread = threading.Thread(target=read)
    thread.start()
    assert started.wait(timeout=2)
    begin = time.perf_counter()
    catalog.close()
    elapsed = time.perf_counter() - begin
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert errors == []
    assert finished.is_set()
    assert elapsed >= 0.15


async def test_owner_read_write_lock_mode_serves_concurrent_reads_and_writes():
    from app.services.overgraph.owner import OvergraphOwner, OwnerClient

    root = Path(tempfile.mkdtemp(prefix="owner-rw-"))
    owner = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    owner.lock_mode = "read_write"
    owner.read_workers = 2
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    try:
        await client.mutate("rw-seed", {"upsert_nodes": [{
            "labels": [FACT, scope_label("customer:1")], "key": "rw-0",
            "props": {"scope_key": "customer:1", "status": "active"},
        }]}, kind="batch")

        async def read_loop() -> None:
            for _ in range(20):
                await client.query_nodes(FACT, limit=10)

        reads = [asyncio.create_task(read_loop()) for _ in range(4)]
        writes = [client.mutate(f"rw-write-{index}", {"upsert_nodes": [{
            "labels": [FACT, scope_label("customer:1")], "key": f"rw-{index}",
            "props": {"scope_key": "customer:1", "status": "active"},
        }]}, kind="batch") for index in range(20)]
        results = await asyncio.gather(*reads, *writes, return_exceptions=True)
        assert all(not isinstance(result, BaseException) for result in results)
    finally:
        await owner.close()


def test_nested_read_does_not_deadlock_behind_a_waiting_writer():
    root = Path(tempfile.mkdtemp(prefix="catalog-rw-nested-"))
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=4)
    enable_read_write_lock(catalog)
    _seed(catalog)
    entered = threading.Event()
    release = threading.Event()
    writer_started = threading.Event()
    writer_done = threading.Event()
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            def outer(db):
                entered.set()
                release.wait(timeout=2)
                return catalog.count_nodes_by_labels([FACT])

            catalog.read(outer)
        except (OverGraphError, RuntimeError, ValueError, TypeError) as exc:
            errors.append(exc)

    def writer() -> None:
        try:
            writer_started.set()
            catalog.upsert_node(
                [FACT, scope_label("customer:1")], "nested-write",
                props={"scope_key": "customer:1", "status": "active"},
            )
        except (OverGraphError, RuntimeError, ValueError, TypeError) as exc:
            errors.append(exc)
        finally:
            writer_done.set()

    reader_thread = threading.Thread(target=reader)
    writer_thread = threading.Thread(target=writer)
    reader_thread.start()
    assert entered.wait(timeout=2)
    writer_thread.start()
    assert writer_started.wait(timeout=2)
    time.sleep(0.05)
    release.set()
    reader_thread.join(timeout=2)
    writer_thread.join(timeout=2)
    try:
        assert not reader_thread.is_alive()
        assert writer_done.is_set()
        assert errors == []
    finally:
        catalog.close()


def test_write_inside_read_callback_raises_instead_of_deadlocking():
    from app.services.overgraph.owner_locks import ReadWriteLock

    lock = ReadWriteLock()
    with lock.reader():
        with pytest.raises(RuntimeError):
            with lock:
                pass


def test_mode_switch_waits_for_an_inflight_read():
    from app.services.overgraph.owner_locks import ReadWriteLock

    root = Path(tempfile.mkdtemp(prefix="catalog-rw-switch-"))
    catalog = open_catalog(root / "catalog", kind="knowledge", dimension=4)
    _seed(catalog)
    entered = threading.Event()
    release = threading.Event()
    switched = threading.Event()

    def reader() -> None:
        catalog.read(lambda db: (entered.set(), release.wait(timeout=2)))

    def switch() -> None:
        enable_read_write_lock(catalog)
        switched.set()

    reader_thread = threading.Thread(target=reader)
    switch_thread = threading.Thread(target=switch)
    reader_thread.start()
    assert entered.wait(timeout=2)
    switch_thread.start()
    time.sleep(0.05)
    assert not switched.is_set()
    release.set()
    reader_thread.join(timeout=2)
    switch_thread.join(timeout=2)
    try:
        assert switched.is_set()
        assert isinstance(catalog._lock, ReadWriteLock)
    finally:
        catalog.close()


def test_read_inside_writer_is_allowed():
    from app.services.overgraph.owner_locks import ReadWriteLock

    lock = ReadWriteLock()
    with lock:
        with lock.reader():
            pass
