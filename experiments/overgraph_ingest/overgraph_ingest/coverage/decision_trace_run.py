"""Inspect saved coverage JSON for decision traces. No new Jev. No controller."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.decision_trace import (
    BLIND_RUN_CANDIDATES,
    TRACE_BASELINE_ID,
    TRACE_BASELINE_PATH,
    inspect_saved_run,
)

ROOT = Path(__file__).resolve().parents[2]
FIRST_100_NAMED_ONLY = ROOT / "data" / "coverage-v3-relation-carveout.json"


def run_decision_trace(*, run_path: Path | None = None) -> dict[str, object]:
    blind_path = next((path for path in BLIND_RUN_CANDIDATES if path.is_file()), None)
    chosen = run_path or blind_path
    if chosen is None:
        inspect = {
            "observability_gap": True,
            "named_paths_without_units": [],
            "cannot_read_jev_yes_unit": True,
            "cannot_read_hop": True,
            "cannot_attribute_error_class": True,
            "do_not_guess_documents": True,
        }
    else:
        inspect = inspect_saved_run(json.loads(chosen.read_text(encoding="utf-8")))
    first_100 = None
    if FIRST_100_NAMED_ONLY.is_file():
        first_100 = inspect_saved_run(json.loads(FIRST_100_NAMED_ONLY.read_text(encoding="utf-8")))
        first_100["note"] = "first-100 relation run names, not the blind false completes"
    return {
        "operation": "coverage",
        "experiment": "decision_trace_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_jev": True,
        "no_link_re_change": True,
        "no_looser_verified_rule": True,
        "blind_run_not_in_workspace": next((path for path in BLIND_RUN_CANDIDATES if path.is_file()), None)
        is None,
        "run_path": None if chosen is None else str(chosen),
        "inspect": inspect,
        "first_100_named_paths_are_not_blind": first_100,
        "next": "rerun coverage v3 with --decision-trace; do not guess document ids",
    }


def freeze_decision_trace_baseline(payload: dict[str, object]) -> dict[str, object]:
    inspect = payload.get("inspect") or {}
    return {
        "id": TRACE_BASELINE_ID,
        "label": (
            "Frozen: blind coverage traces are missing. Observability added. "
            "Do not attribute unobserved documents."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_jev": True,
        "no_link_re_change": True,
        "headline": {
            "observability_gap": inspect.get("observability_gap"),
            "blind_run_not_in_workspace": payload.get("blind_run_not_in_workspace"),
            "named_paths_without_units": inspect.get("named_paths_without_units"),
            "do_not_guess_documents": inspect.get("do_not_guess_documents"),
        },
        "next": payload.get("next"),
    }


def write_decision_trace_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or TRACE_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_decision_trace_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
