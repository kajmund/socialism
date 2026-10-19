"""Pinned implicit SQLite contract for camel-oasis simulation.db."""

from __future__ import annotations

SCHEMA_VERSION = "0.2.5"

# Tables required for post-run variant export (readback).
EXPORT_TABLES: frozenset[str] = frozenset(
    {
        "post",
        "comment",
        "like",
        "dislike",
        "comment_like",
        "comment_dislike",
        "follow",
        "mute",
        "report",
        "trace",
    }
)
