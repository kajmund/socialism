"""Postgres implementation of Mem0 OSS's synchronous history-store contract."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class PostgresHistoryManager:
    def __init__(self, connection_string: str) -> None:
        self._connection = psycopg.connect(connection_string)
        self._lock = threading.Lock()

    def add_history(
        self,
        memory_id: str,
        old_memory: str | None,
        new_memory: str | None,
        event: str,
        *,
        created_at: str | None = None,
        updated_at: str | None = None,
        is_deleted: int = 0,
        actor_id: str | None = None,
        role: str | None = None,
    ) -> None:
        self.batch_add_history(
            [
                {
                    "memory_id": memory_id,
                    "old_memory": old_memory,
                    "new_memory": new_memory,
                    "event": event,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "is_deleted": is_deleted,
                    "actor_id": actor_id,
                    "role": role,
                }
            ]
        )

    def batch_add_history(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        with self._lock, self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO mem0_history (
                    id, memory_id, old_memory, new_memory, event,
                    created_at, updated_at, is_deleted, actor_id, role
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        str(uuid.uuid4()),
                        record.get("memory_id"),
                        record.get("old_memory"),
                        record.get("new_memory"),
                        record.get("event"),
                        record.get("created_at"),
                        record.get("updated_at"),
                        bool(record.get("is_deleted", 0)),
                        record.get("actor_id"),
                        record.get("role"),
                    )
                    for record in records
                ],
            )

    def get_history(self, memory_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, memory_id, old_memory, new_memory, event,
                       created_at, updated_at, is_deleted, actor_id, role
                FROM mem0_history
                WHERE memory_id = %s
                ORDER BY created_at ASC NULLS FIRST, updated_at ASC NULLS FIRST
                """,
                (memory_id,),
            )
            return [
                {
                    "id": row[0],
                    "memory_id": row[1],
                    "old_memory": row[2],
                    "new_memory": row[3],
                    "event": row[4],
                    "created_at": row[5],
                    "updated_at": row[6],
                    "is_deleted": row[7],
                    "actor_id": row[8],
                    "role": row[9],
                }
                for row in cursor.fetchall()
            ]

    def save_messages(self, messages: list[dict[str, Any]], session_scope: str) -> None:
        if not messages:
            return
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO mem0_messages
                    (id, session_scope, role, content, name, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        str(uuid.uuid4()),
                        session_scope,
                        message.get("role"),
                        Jsonb(message.get("content")),
                        message.get("name"),
                        now,
                    )
                    for message in messages
                ],
            )
            cursor.execute(
                """
                DELETE FROM mem0_messages
                WHERE session_scope = %s
                  AND id NOT IN (
                    SELECT id FROM mem0_messages
                    WHERE session_scope = %s
                    ORDER BY created_at DESC
                    LIMIT 10
                  )
                """,
                (session_scope, session_scope),
            )

    def get_last_messages(
        self, session_scope: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        with self._lock, self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT role, content, name, created_at FROM (
                    SELECT role, content, name, created_at
                    FROM mem0_messages
                    WHERE session_scope = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                ) recent
                ORDER BY created_at ASC
                """,
                (session_scope, limit),
            )
            return [
                {
                    "role": row[0],
                    "content": row[1],
                    "name": row[2],
                    "created_at": row[3],
                }
                for row in cursor.fetchall()
            ]

    def reset(self) -> None:
        with self._lock, self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.execute("TRUNCATE mem0_history, mem0_messages")

    def close(self) -> None:
        with self._lock:
            if not self._connection.closed:
                self._connection.close()

    def __del__(self) -> None:
        self.close()
