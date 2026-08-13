"""Unit tests for simulation/artifact reader (no camel-oasis)."""

import sqlite3
from pathlib import Path

import pytest

from app.services.simulation.artifact.reader import (
    OasisArtifactError,
    OasisArtifactReader,
    created_at_to_sort_key,
    read_oasis_results,
)
from app.services.simulation.artifact.schema import EXPORT_TABLES, SCHEMA_VERSION


def _create_export_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE user (user_id INTEGER PRIMARY KEY, agent_id INTEGER, num_followers INTEGER, num_followings INTEGER);
        CREATE TABLE post (
            post_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            original_post_id INTEGER,
            content TEXT,
            quote_content TEXT,
            num_likes INTEGER,
            num_dislikes INTEGER,
            num_shares INTEGER,
            created_at TEXT
        );
        CREATE TABLE comment (
            comment_id INTEGER PRIMARY KEY,
            post_id INTEGER,
            user_id INTEGER,
            content TEXT,
            num_likes INTEGER,
            num_dislikes INTEGER,
            created_at TEXT
        );
        CREATE TABLE like (like_id INTEGER PRIMARY KEY, user_id INTEGER, post_id INTEGER);
        CREATE TABLE dislike (
            dislike_id INTEGER PRIMARY KEY, user_id INTEGER, post_id INTEGER
        );
        CREATE TABLE comment_like (
            comment_like_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            comment_id INTEGER
        );
        CREATE TABLE comment_dislike (
            comment_dislike_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            comment_id INTEGER
        );
        CREATE TABLE follow (
            follow_id INTEGER PRIMARY KEY,
            follower_id INTEGER,
            followee_id INTEGER,
            created_at TEXT
        );
        CREATE TABLE mute (
            mute_id INTEGER PRIMARY KEY,
            muter_id INTEGER,
            mutee_id INTEGER,
            created_at TEXT
        );
        CREATE TABLE report (
            report_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            post_id INTEGER,
            report_reason TEXT,
            created_at TEXT
        );
        CREATE TABLE trace (
            user_id INTEGER,
            created_at TEXT,
            action TEXT,
            info TEXT
        );
        """
    )


def test_created_at_to_sort_key_handles_timestep_and_iso():
    assert created_at_to_sort_key(12) == 12
    assert created_at_to_sort_key("12") == 12
    iso = created_at_to_sort_key("2026-08-01 00:00:00.001")
    assert iso is not None
    assert iso > 1_000_000_000_000


def test_export_variant_payload_matches_legacy_shape(tmp_path: Path):
    db_path = tmp_path / "simulation.db"
    conn = sqlite3.connect(db_path)
    try:
        _create_export_schema(conn)
        conn.execute(
            "INSERT INTO post VALUES (1, 0, NULL, 'hej', NULL, 1, 0, 0, '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO follow VALUES (1, 2, 0, '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO trace VALUES (2, '2026-01-01', 'follow', '{}')"
        )
        conn.execute(
            "INSERT INTO trace VALUES (2, '2026-01-02', 'like_post', '{}')"
        )
        conn.commit()
    finally:
        conn.close()

    payload = OasisArtifactReader(db_path).export_variant_payload()
    assert len(payload["posts"]) == 1
    assert payload["follows"][0]["follower_id"] == 2
    assert {"action": "like_post", "count": 1} in payload["action_histogram"]
    assert {"action": "follow", "count": 1} in payload["action_histogram"]


def test_missing_db_returns_empty_payload(tmp_path: Path):
    payload = read_oasis_results(tmp_path / "missing.db")
    assert payload["posts"] == []
    assert payload["action_histogram"] == []


def test_assert_export_schema_fails_on_missing_tables(tmp_path: Path):
    db_path = tmp_path / "simulation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE post (post_id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()

    reader = OasisArtifactReader(db_path)
    with pytest.raises(OasisArtifactError, match=SCHEMA_VERSION):
        reader.assert_export_schema()

    missing = sorted(EXPORT_TABLES - {"post"})
    assert "comment" in missing


def test_user_follow_counts(tmp_path: Path):
    db_path = tmp_path / "simulation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE user (agent_id INTEGER PRIMARY KEY, num_followers INTEGER, num_followings INTEGER)"
        )
        conn.execute(
            "INSERT INTO user VALUES (3, 12, 4)"
        )
        conn.commit()
    finally:
        conn.close()

    reader = OasisArtifactReader(db_path)
    assert reader.user_follower_count(3) == 12
    assert reader.user_following_count(3) == 4


def test_user_follow_counts_degrade_when_user_table_missing(tmp_path: Path):
    db_path = tmp_path / "simulation.db"
    sqlite3.connect(db_path).close()

    reader = OasisArtifactReader(db_path)
    assert reader.user_follower_count(1) == 0
    assert reader.user_following_count(1) == 0


def test_export_variant_payload_fails_on_column_mismatch(tmp_path: Path):
    db_path = tmp_path / "simulation.db"
    conn = sqlite3.connect(db_path)
    try:
        _create_export_schema(conn)
        conn.execute("DROP TABLE post")
        conn.execute("CREATE TABLE post (id INTEGER PRIMARY KEY, body TEXT)")
        conn.commit()
    finally:
        conn.close()

    reader = OasisArtifactReader(db_path)
    with pytest.raises(OasisArtifactError, match=SCHEMA_VERSION):
        reader.export_variant_payload()


def test_max_event_time_iso_datetime(tmp_path: Path):
    db_path = tmp_path / "simulation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE post (
                post_id INTEGER PRIMARY KEY,
                created_at TEXT
            );
            CREATE TABLE trace (
                user_id INTEGER,
                created_at TEXT,
                action TEXT,
                info TEXT
            );
            INSERT INTO post (post_id, created_at)
            VALUES (1, '2026-08-01 00:00:00.001');
            INSERT INTO trace (user_id, created_at, action, info)
            VALUES (1, '2026-08-01 00:00:00.005', 'like_post', '{}');
            """
        )
        conn.commit()
    finally:
        conn.close()

    end = OasisArtifactReader(db_path).max_event_time()
    assert end == created_at_to_sort_key("2026-08-01 00:00:00.005")
