"""Scripted Tabular Review bench. Not a live model quality claim."""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.services.knowledge.units import TextUnit, hash_text
from app.services.tabular_review.ranking import ColumnScoreOptions, score_document_column
from app.services.tabular_review.types import CellDecision


def scripted_unit(document_id: str, text: str, *, hit: bool) -> tuple[TextUnit, list[float]]:
    unit = TextUnit(
        id=f"{document_id}-u0",
        document_version_id=f"{document_id}-v",
        document_id=document_id,
        section_id=None,
        ordinal=0,
        text=text,
        content_hash=hash_text(text),
        locator="§1" if hit else None,
        page_start=1 if hit else None,
    )
    vector = [1.0, 0.0] if hit else [0.0, 1.0]
    return unit, vector


def run_scripted_table(
    *,
    document_count: int = 200,
    columns: Sequence[str] = ("uppsagning", "pris"),
    golden_hits: Sequence[int] | None = None,
    threshold: float = 0.35,
) -> dict[str, object]:
    """Score many documents with fixed vectors. Reports latency, not model quality."""
    hits = set(golden_hits or range(0, document_count, 4))
    started = time.perf_counter()
    first_row_at: float | None = None
    decisions: list[CellDecision] = []
    recovered = 0
    expected = 0
    for index in range(document_count):
        document_id = f"doc-{index:03d}"
        is_hit = index in hits
        unit, vector = scripted_unit(
            document_id,
            "tre månaders uppsägningstid" if is_hit else "samråd om leverans",
            hit=is_hit,
        )
        for _column in columns:
            decision = score_document_column(
                [unit],
                {unit.id: vector},
                [[1.0, 0.0]],
                ColumnScoreOptions(polarity="positive", threshold=threshold),
            )
            decisions.append(decision)
            if is_hit:
                expected += 1
                if decision.status == "hit":
                    recovered += 1
        if first_row_at is None:
            first_row_at = time.perf_counter() - started
    elapsed = time.perf_counter() - started
    return {
        "kind": "scripted",
        "not_live_model_quality": True,
        "documents": document_count,
        "columns": list(columns),
        "cells": len(decisions),
        "first_table_seconds": first_row_at or elapsed,
        "ssr_seconds": elapsed,
        "recall": recovered / expected if expected else 0.0,
        "expected_hits": expected,
        "recovered_hits": recovered,
        "no_hit": sum(1 for item in decisions if item.status == "no_hit"),
    }
