"""Stable knowledge identity. Scope + normalized assertion only."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_VOLATILE_KEYS = frozenset(
    {
        "attempt_id",
        "citation",
        "citations",
        "created_at",
        "display",
        "excerpt",
        "explanation",
        "interpretation",
        "observation_kind",
        "persistence_class",
        "prose",
        "question",
        "question_key",
        "question_text",
        "quote",
        "quotes",
        "rationale",
        "raw_text",
        "research_need_id",
        "result_id",
        "run_id",
        "source_attempt_id",
        "statement_display",
        "timestamp",
        "updated_at",
        "wording",
    }
)
_PUNCT_EDGE = re.compile(r"^[\s.,;:!?\"'()\[\]«»]+|[\s.,;:!?\"'()\[\]«»]+$")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_assertion_text(text: str) -> str:
    collapsed = " ".join(text.casefold().split())
    return _PUNCT_EDGE.sub("", collapsed)


def normalize_assertion(value: Any) -> Any:
    """Drop volatile prose/run keys and normalize strings for identity."""
    if isinstance(value, dict):
        return {
            str(key): normalize_assertion(item)
            for key, item in value.items()
            if str(key).casefold() not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [normalize_assertion(item) for item in value]
    if isinstance(value, str):
        return normalize_assertion_text(value)
    return value


def knowledge_claim_identity(
    *,
    scope_key: str,
    predicate: str,
    value: dict[str, object],
) -> str:
    payload = (
        f"{scope_key}\0{predicate.strip()}\0{canonical_json(normalize_assertion(value))}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def knowledge_observation_id(
    *,
    scope_key: str,
    observation_class: str,
    kind: str,
    document_version_id: str,
    question_key: str,
    statement_normalized: str,
) -> str:
    payload = (
        f"{scope_key}\0{observation_class}\0{kind}\0"
        f"{document_version_id}\0{question_key}\0{statement_normalized}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
