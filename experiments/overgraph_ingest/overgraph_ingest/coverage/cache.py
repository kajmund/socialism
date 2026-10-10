"""Reuse earlier isolated classify judgments. Same unit is never re-asked."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.jev.questions import Label


@dataclass(frozen=True)
class CachedAnswer:
    predicted: Label
    confidence: float | None
    source: str


def load_gold_cache(path: Path, *, source: str) -> dict[str, CachedAnswer]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = _judgment_rows(payload)
    cache: dict[str, CachedAnswer] = {}
    for row in rows:
        key = str(row.get("key") or "")
        predicted = str(row.get("predicted") or "").upper()
        if not key or predicted not in {"YES", "NO", "UNCERTAIN"}:
            continue
        confidence = row.get("confidence")
        cache[key] = CachedAnswer(
            predicted=predicted,  # type: ignore[arg-type]
            confidence=None if confidence is None else float(confidence),
            source=source,
        )
    return cache


def _judgment_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    runs = list(payload.get("runs") or [])
    chosen = None
    for run in runs:
        if run.get("variant") == "C@8" or (
            run.get("concurrency") == 8 and run.get("batch_size") in {1, None}
        ):
            chosen = run
            break
    if chosen is None and runs:
        chosen = runs[0]
    if chosen is None:
        return []
    return [dict(row) for row in (chosen.get("wall_judgments") or [])]
