"""Build run-watch replay payloads from DB live_progress + simulation.db."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database.models import PopulationMember, Run
from app.schemas.domain import Tick
from app.services.oasis_engagement import read_trace_range
from app.services.oasis_profiles import watch_agent_roster
from app.services.run_plans import variant_plans
from app.services.run_live_progress import read_live_progress
from app.services.run_trace_enrich import (
    activity_items_from_trace_rows,
    enrich_trace_rows,
)

ARTIFACT_ROOT = Path("data/oasis")


def variant_artifact_db(run_id: int, variant_id: str) -> Path:
    return ARTIFACT_ROOT / f"run_{run_id}" / variant_id / "simulation.db"


def ticks_for_variant(run: Run, variant_id: str) -> list[Tick]:
    for plan_id, _label, ticks in variant_plans(run):
        if plan_id == variant_id:
            return ticks
    return []


def build_run_replay_payload(
    run: Run,
    *,
    variant_id: str,
    members: list[PopulationMember] | None = None,
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
        "agents": watch_agent_roster(members or [], ticks_for_variant(run, variant_id)),
        "rounds": rounds,
    }


def snapshot_live_feed_rounds(run: Run, variant_id: str) -> list[dict[str, Any]]:
    """Freeze the live-watch rounds for storage on the attempt variant."""
    return build_run_replay_payload(run, variant_id=variant_id)["rounds"]
