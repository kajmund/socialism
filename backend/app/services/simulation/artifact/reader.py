"""Read camel-oasis simulation.db behind a typed, schema-checked boundary."""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.simulation.artifact.schema import EXPORT_TABLES, SCHEMA_VERSION
from app.services.simulation.artifact.time import created_at_to_sort_key


class OasisArtifactError(RuntimeError):
    """simulation.db exists but does not match the pinned camel-oasis schema."""


class OasisArtifactReader:
    """All SQLite access to a single simulation.db artifact."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        return self._db_path

    def exists(self) -> bool:
        return self._db_path.exists()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _table_rows(
        conn: sqlite3.Connection, sql: str, *, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        try:
            if params is None:
                rows = conn.execute(sql)
            else:
                rows = conn.execute(sql, params)
            return [dict(row) for row in rows]
        except sqlite3.OperationalError as exc:
            raise OasisArtifactError(
                f"simulation.db schema mismatch (expected camel-oasis {SCHEMA_VERSION}): "
                f"export query failed: {exc}"
            ) from exc

    def assert_export_schema(self) -> None:
        """Fail loud when export tables are missing (camel-oasis upgrade drift)."""
        if not self._db_path.exists():
            return
        conn = self._connect()
        try:
            present = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
        missing = sorted(EXPORT_TABLES - present)
        if missing:
            raise OasisArtifactError(
                f"simulation.db schema mismatch (expected camel-oasis {SCHEMA_VERSION}): "
                f"missing tables {missing}"
            )

    def export_variant_payload(self) -> dict[str, Any]:
        """Full readback payload for a completed variant (posts, trace, histogram, …)."""
        if not self._db_path.exists():
            return _empty_variant_payload()
        self.assert_export_schema()
        conn = self._connect()
        try:
            posts = self._table_rows(
                conn,
                "SELECT post_id, user_id, original_post_id, content, "
                "quote_content, num_likes, num_dislikes, num_shares, "
                "created_at FROM post ORDER BY post_id",
            )
            comments = self._table_rows(
                conn,
                "SELECT comment_id, post_id, user_id, content, "
                "num_likes, num_dislikes, created_at FROM comment "
                "ORDER BY comment_id",
            )

            likes_by_post: dict[int, list[int]] = {}
            for row in self._table_rows(
                conn, "SELECT user_id, post_id FROM like ORDER BY like_id"
            ):
                likes_by_post.setdefault(int(row["post_id"]), []).append(
                    int(row["user_id"])
                )

            dislikes_by_post: dict[int, list[int]] = {}
            for row in self._table_rows(
                conn, "SELECT user_id, post_id FROM dislike ORDER BY dislike_id"
            ):
                dislikes_by_post.setdefault(int(row["post_id"]), []).append(
                    int(row["user_id"])
                )

            comment_likes_by_id: dict[int, list[int]] = {}
            for row in self._table_rows(
                conn,
                "SELECT user_id, comment_id FROM comment_like "
                "ORDER BY comment_like_id",
            ):
                comment_likes_by_id.setdefault(int(row["comment_id"]), []).append(
                    int(row["user_id"])
                )

            comment_dislikes_by_id: dict[int, list[int]] = {}
            for row in self._table_rows(
                conn,
                "SELECT user_id, comment_id FROM comment_dislike "
                "ORDER BY comment_dislike_id",
            ):
                comment_dislikes_by_id.setdefault(
                    int(row["comment_id"]), []
                ).append(int(row["user_id"]))

            shares_by_post: dict[int, list[dict[str, Any]]] = {}
            for post in posts:
                original_id = post.get("original_post_id")
                if original_id is None:
                    continue
                quote = (post.get("quote_content") or "").strip()
                shares_by_post.setdefault(int(original_id), []).append(
                    {
                        "user_id": int(post["user_id"]),
                        "kind": "quote" if quote else "repost",
                        "share_post_id": int(post["post_id"]),
                    }
                )

            for post in posts:
                pid = int(post["post_id"])
                post["liked_by"] = likes_by_post.get(pid, [])
                post["disliked_by"] = dislikes_by_post.get(pid, [])
                post["shared_by"] = shares_by_post.get(pid, [])

            for comment in comments:
                cid = int(comment["comment_id"])
                comment["liked_by"] = comment_likes_by_id.get(cid, [])
                comment["disliked_by"] = comment_dislikes_by_id.get(cid, [])

            follows = self._table_rows(
                conn,
                "SELECT follow_id, follower_id, followee_id, created_at FROM follow "
                "ORDER BY follow_id",
            )
            mutes = self._table_rows(
                conn,
                "SELECT mute_id, muter_id, mutee_id, created_at FROM mute "
                "ORDER BY mute_id",
            )
            reports = self._table_rows(
                conn,
                "SELECT report_id, user_id, post_id, report_reason, created_at "
                "FROM report ORDER BY report_id",
            )
            trace = self._table_rows(
                conn,
                "SELECT user_id, created_at, action, info FROM trace "
                "ORDER BY created_at, user_id",
            )
        finally:
            conn.close()
        return {
            "posts": posts,
            "comments": comments,
            "follows": follows,
            "mutes": mutes,
            "reports": reports,
            "trace": trace,
            "action_histogram": action_histogram(trace),
        }

    def max_post_id(self) -> int:
        if not self._db_path.exists():
            return 0
        conn = self._connect()
        try:
            row = conn.execute("SELECT MAX(post_id) FROM post").fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()

    def injector_post_ids_after(
        self,
        *,
        injector_indices: set[int],
        after_post_id: int,
    ) -> frozenset[int]:
        if not self._db_path.exists() or not injector_indices:
            return frozenset()
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in injector_indices)
            sql = (
                f"SELECT post_id FROM post WHERE post_id > ? "
                f"AND user_id IN ({placeholders})"
            )
            params: list[Any] = [after_post_id, *sorted(injector_indices)]
            rows = conn.execute(sql, params).fetchall()
            return frozenset(int(r[0]) for r in rows)
        except sqlite3.OperationalError:
            return frozenset()
        finally:
            conn.close()

    def trace_row_count(self) -> int:
        if not self._db_path.exists():
            return 0
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM trace").fetchone()
            return int(row[0]) if row else 0
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()

    def read_trace_since(self, after_count: int) -> list[dict[str, Any]]:
        if not self._db_path.exists():
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT user_id, created_at, action, info FROM trace "
                "ORDER BY rowid LIMIT -1 OFFSET ?",
                (max(0, after_count),),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def read_trace_range(self, start: int, end: int) -> list[dict[str, Any]]:
        """Read trace rows for one round using the same rowid ordering as trace_row_count."""
        if not self._db_path.exists() or end <= start:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT user_id, created_at, action, info FROM trace "
                "ORDER BY rowid LIMIT ? OFFSET ?",
                (end - start, max(0, start)),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def post_contents(self, post_ids: set[int]) -> dict[int, str]:
        if not self._db_path.exists() or not post_ids:
            return {}
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in post_ids)
            sql = (
                f"SELECT post_id, content FROM post "
                f"WHERE post_id IN ({placeholders})"
            )
            rows = conn.execute(sql, sorted(post_ids)).fetchall()
            return {int(r[0]): str(r[1] or "") for r in rows}
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()

    def comment_contents(self, comment_ids: set[int]) -> dict[int, str]:
        if not self._db_path.exists() or not comment_ids:
            return {}
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in comment_ids)
            sql = (
                f"SELECT comment_id, content FROM comment "
                f"WHERE comment_id IN ({placeholders})"
            )
            rows = conn.execute(sql, sorted(comment_ids)).fetchall()
            return {int(r[0]): str(r[1] or "") for r in rows}
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()

    def comment_post_ids(self, comment_ids: set[int]) -> dict[int, int]:
        if not self._db_path.exists() or not comment_ids:
            return {}
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in comment_ids)
            sql = (
                f"SELECT comment_id, post_id FROM comment "
                f"WHERE comment_id IN ({placeholders})"
            )
            rows = conn.execute(sql, sorted(comment_ids)).fetchall()
            return {int(r[0]): int(r[1]) for r in rows}
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()

    def followee_ids_by_follow_id(self, follow_ids: set[int]) -> dict[int, int]:
        """Resolve OASIS follow trace rows that only carry follow_id."""
        if not self._db_path.exists() or not follow_ids:
            return {}
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in follow_ids)
            sql = (
                f"SELECT follow_id, followee_id FROM follow "
                f"WHERE follow_id IN ({placeholders})"
            )
            rows = conn.execute(sql, sorted(follow_ids)).fetchall()
            return {int(r[0]): int(r[1]) for r in rows}
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()

    def report_reasons_by_report_id(self, report_ids: set[int]) -> dict[int, str]:
        if not self._db_path.exists() or not report_ids:
            return {}
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in report_ids)
            sql = (
                f"SELECT report_id, report_reason FROM report "
                f"WHERE report_id IN ({placeholders})"
            )
            rows = conn.execute(sql, sorted(report_ids)).fetchall()
            return {int(r[0]): str(r[1] or "") for r in rows}
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()

    def max_event_time(self) -> int:
        """Highest created_at in trace/post, or -1 when empty."""
        if not self._db_path.exists():
            return -1
        conn = self._connect()
        try:
            times: list[int] = []
            for sql in (
                "SELECT created_at FROM trace",
                "SELECT created_at FROM post",
            ):
                try:
                    rows = conn.execute(sql).fetchall()
                except sqlite3.OperationalError:
                    continue
                for row in rows:
                    key = created_at_to_sort_key(row[0] if row else None)
                    if key is not None:
                        times.append(key)
            return max(times) if times else -1
        finally:
            conn.close()

    def user_follower_count(self, agent_id: int) -> int:
        """Follower count for Swedish env prompt text (cosmetic, not export data)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT num_followers FROM user WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            # Live sim: user table may be unreadable early in a tick (lock/migration).
            # Degrade to 0 rather than abort an expensive LLM run for prompt garnish.
            return 0
        finally:
            conn.close()

    def user_following_count(self, agent_id: int) -> int:
        """Following count for Swedish env prompt text (cosmetic, not export data)."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT num_followings FROM user WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()


def _empty_variant_payload() -> dict[str, Any]:
    return {
        "posts": [],
        "comments": [],
        "follows": [],
        "mutes": [],
        "reports": [],
        "trace": [],
        "action_histogram": [],
    }


def action_histogram(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in trace:
        action = str(row.get("action") or "").strip()
        if action:
            counts[action] += 1
    return [{"action": action, "count": count} for action, count in counts.most_common()]


def read_oasis_results(db_path: Path) -> dict[str, Any]:
    """Backward-compatible helper — prefer OasisArtifactReader.export_variant_payload()."""
    return OasisArtifactReader(db_path).export_variant_payload()
