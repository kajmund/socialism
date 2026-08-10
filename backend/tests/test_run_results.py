"""Tests for read-only run.results helpers."""

from __future__ import annotations

from app.services.run_results import find_attempt, find_variant, list_attempts


def test_list_attempts_newest_first_shape():
    results = {
        "engine": "oasis",
        "attempts": [
            {"id": "att_new", "variants": [{"id": "main"}]},
            {"id": "att_old", "variants": [{"id": "main"}]},
        ],
    }
    attempts = list_attempts(results)
    assert [a["id"] for a in attempts] == ["att_new", "att_old"]
    assert find_attempt(results, "att_new") is not None
    assert find_variant(attempts[0], "main")["id"] == "main"


def test_list_attempts_legacy_variants():
    results = {
        "engine": "none",
        "variants": [{"id": "main", "error": None}],
    }
    attempts = list_attempts(results)
    assert len(attempts) == 1
    assert attempts[0]["id"] == "legacy"
