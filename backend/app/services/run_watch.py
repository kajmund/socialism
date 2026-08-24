"""Build run-watch replay payloads from DB live_progress + simulation.db."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database.models import Run
from app.services.oasis_engagement import read_trace_range
from app.services.run_live_progress import read_live_progress
from app.services.run_trace_enrich import (
    activity_items_from_trace_rows,
    enrich_trace_rows,
)

ARTIFACT_ROOT = Path("data/oasis")


def variant_artifact_db(run_id: int, variant_id: str) -> Path:
    return ARTIFACT_ROOT / f"run_{run_id}" / variant_id / "simulation.db"


def build_run_replay_payload(
    run: Run,
    *,
    variant_id: str,
) -> dict[str, Any]:
    db_path = variant_artifact_db(run.id, variant_id)
    rounds: list[dict[str, Any]] = []
    for entry in read_live_progress(run, variant_id):
        trace_start = int(entry.get("trace_start", 0))
        trace_end = int(entry.get("trace_end", 0))
        rows = read_trace_range(db_path, trace_start, trace_end)
        enriched = enrich_trace_rows(db_path, rows)
        rounds.append(
            {
                "tick_index": int(entry.get("tick_index", 0)),
                "round_index": int(entry.get("round_index", 0)),
                "items": activity_items_from_trace_rows(enriched),
            }
        )
    return {
        "type": "run.replay",
        "run_id": run.id,
        "variant_id": variant_id,
        "rounds": rounds,
    }
