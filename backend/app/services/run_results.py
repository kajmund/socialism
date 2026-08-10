"""Read-only helpers for run.results JSON (no OASIS runtime imports)."""

from __future__ import annotations

from typing import Any


def list_attempts(results: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize stored results into an attempts list (newest first)."""
    if not results:
        return []
    attempts = results.get("attempts")
    if isinstance(attempts, list):
        return [a for a in attempts if isinstance(a, dict)]

    if isinstance(results.get("variants"), list):
        legacy = {
            "id": "legacy",
            "finished_at": results.get("finished_at"),
            "engine": results.get("engine"),
            "error": results.get("error"),
            "variants": results.get("variants"),
            "log_dir": results.get("log_dir"),
        }
        return [legacy]
    return []


def find_variant(attempt: dict[str, Any], variant_id: str) -> dict[str, Any] | None:
    variants = attempt.get("variants")
    if not isinstance(variants, list):
        return None
    for variant in variants:
        if isinstance(variant, dict) and str(variant.get("id")) == variant_id:
            return variant
    return None


def find_attempt(results: dict[str, Any] | None, attempt_id: str) -> dict[str, Any] | None:
    for attempt in list_attempts(results):
        if str(attempt.get("id")) == attempt_id:
            return attempt
    return None
