from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from app.services.expertgranskning.mem0_postgres_history import PostgresHistoryManager


def _mock_connection() -> MagicMock:
    connection = MagicMock()
    connection.closed = False
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    connection.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
    connection.transaction.return_value.__enter__ = MagicMock(return_value=None)
    connection.transaction.return_value.__exit__ = MagicMock(return_value=False)
    return connection


def test_postgres_history_manager_serializes_concurrent_reads():
    connection = _mock_connection()
    with patch(
        "app.services.expertgranskning.mem0_postgres_history.psycopg.connect",
        return_value=connection,
    ):
        manager = PostgresHistoryManager("postgresql://example.test/db")

    active = 0
    max_active = 0
    counter_lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker() -> None:
        nonlocal active, max_active
        barrier.wait()
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            manager.get_history("memory-1")
        finally:
            with counter_lock:
                active -= 1

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == 1
