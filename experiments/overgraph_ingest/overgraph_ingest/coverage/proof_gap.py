"""Distance from first signal to complete proof. Replay only. No new Jev."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.cache import load_c8_judgments
from overgraph_ingest.coverage.v2 import DEFAULT_CACHE
from overgraph_ingest.navigation.hop import PUNKT_RE
from overgraph_ingest.retrieval.gold import RetrievalGold, load_gold_suite

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V3 = ROOT / "data" / "coverage-v3.json"
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
DEFAULT_NAVIGATE = ROOT / "data" / "navigate-avtal-46-49.json"
WORK_KINDS = {
    "discovery": "find_unseen_relevant_documents",
    "proof_completion": "finish_known_evidence",
}


def ranking_gaps(gold: RetrievalGold, payload: dict[str, object]) -> dict[str, object]:
    rows = sorted(
        load_c8_judgments(payload),
        key=lambda row: (int(row.get("rank") or 10**9), str(row.get("key") or "")),
    )
    groups = {group.relative_path: group.contains for group in gold.coverage_groups}
    c8_groups = _c8_group_notes(payload)
    documents = []
    for path in gold.relevant_documents:
        signal = _first(rows, path, verified=False)
        verified = _first(rows, path, verified=True)
        parts = groups.get(path, ())
        found_parts = [
            part for part in parts if any(part in str(row.get("text") or "") for row in rows)
        ]
        needed = len(parts) if parts else 1
        have = len(found_parts) if parts else (1 if verified else 0)
        reference = _punkt(signal)
        missing = bool(signal) and ((bool(parts) and have < needed) or reference is not None)
        hop = _hop_hint(path, c8_groups, reference)
        documents.append(
            {
                "relative_path": path,
                "first_signal_rank": None if signal is None else signal.get("rank"),
                "first_signal_predicted": None if signal is None else signal.get("predicted"),
                "first_verified_rank": None if verified is None else verified.get("rank"),
                "parts_needed": needed,
                "parts_found": have,
                "missing_complementary_passage": missing,
                "hop_possible": hop is not None,
                "hop_relation": None if hop is None else hop.get("relation"),
                "hop_note": None if hop is None else hop.get("note"),
                "work_kind": (
                    "discovery"
                    if signal is None
                    else ("proof_completion" if missing else "already_complete")
                ),
            }
        )
    incomplete = [row for row in documents if row["missing_complementary_passage"]]
    hoppable = [row for row in incomplete if row["hop_possible"]]
    unseen = [row for row in documents if row["first_signal_rank"] is None]
    return {
        "gold_id": gold.id,
        "proof_kind": gold.proof_kind,
        "source": "c8_ranking",
        "relevant_documents": len(documents),
        "documents_with_signal": sum(1 for row in documents if row["first_signal_rank"] is not None),
        "missing_complementary_passage": len(incomplete),
        "hop_possible": len(hoppable),
        "unseen_relevant_documents": [row["relative_path"] for row in unseen],
        "open_references": _open_references(rows),
        "documents": documents,
    }


def workspace_gap(gold_row: dict[str, object]) -> dict[str, object]:
    budgets = list(gold_row.get("budgets") or [])
    last = budgets[-1] if budgets else {}
    timeline = list(last.get("timeline") or [])
    expected = int(last.get("documents_expected") or 0)
    first_yes = next(
        (point for point in timeline if int(point.get("documents_found") or 0) >= expected),
        None,
    )
    first_complete = next(
        (point for point in timeline if not point.get("unresolved_relevant")),
        None,
    )
    yes_at = None if first_yes is None else int(first_yes.get("classified") or 0)
    complete_at = None if first_complete is None else int(first_complete.get("classified") or 0)
    hops = {
        key: value
        for key, value in (last.get("action_counts") or {}).items()
        if str(key).startswith("hop:")
    }
    return {
        "gold_id": gold_row.get("gold_id"),
        "proof_kind": gold_row.get("proof_kind"),
        "source": "coverage_v3_last_budget",
        "first_all_jev_yes_at": yes_at,
        "first_complete_evidence_at": complete_at,
        "classifications_between_yes_and_complete": (
            None if yes_at is None or complete_at is None else complete_at - yes_at
        ),
        "hop_fetches": last.get("hop_fetches"),
        "hop_actions": hops,
        "replay_of_observed_path": True,
    }


def run_proof_gap(
    *,
    cache_root: Path | None = None,
    coverage_v3_path: Path | None = None,
    gold_dir: Path | None = None,
    navigate_path: Path | None = None,
) -> dict[str, object]:
    root = cache_root or ROOT
    golds = {item.id: item for item in load_gold_suite(gold_dir or DEFAULT_GOLD_DIR)}
    coverage = json.loads((coverage_v3_path or DEFAULT_V3).read_text(encoding="utf-8"))
    coverage_by_id = {item.get("gold_id"): item for item in coverage.get("golds") or []}
    navigate = _load_navigate(navigate_path or DEFAULT_NAVIGATE)
    rows = []
    for gold_id, relative in DEFAULT_CACHE.items():
        gold = golds[gold_id]
        c8 = json.loads((root / relative).read_text(encoding="utf-8"))
        ranking = ranking_gaps(gold, c8)
        ranking["source_path"] = str(relative)
        if gold_id == "liability-secrecy-carveout":
            _attach_measured_hops(ranking, navigate)
        rows.append(
            {
                "gold_id": gold_id,
                "ranking": ranking,
                "workspace": workspace_gap(coverage_by_id.get(gold_id) or {}),
            }
        )
    return {
        "operation": "coverage",
        "experiment": "proof_gap_v1",
        "coverage_v3_unchanged": True,
        "classify_unchanged": True,
        "does_not_replace_c8": True,
        "no_new_stop_rule": True,
        "no_new_controller": True,
        "replay_of_observed_path": True,
        "work_kinds": dict(WORK_KINDS),
        "golds": rows,
    }


def _first(
    rows: list[dict[str, object]], path: str, *, verified: bool
) -> dict[str, object] | None:
    for row in rows:
        if row.get("relative_path") != path:
            continue
        if row.get("predicted") not in {"YES", "UNCERTAIN"}:
            continue
        if verified and not (row.get("gold_label") == "relevant" and row.get("predicted") == "YES"):
            continue
        return row
    return None


def _open_references(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    found = []
    seen: set[str] = set()
    for row in rows:
        if row.get("predicted") not in {"YES", "UNCERTAIN"}:
            continue
        reference = _punkt(row)
        if reference is None:
            continue
        path = str(row.get("relative_path") or "")
        if path in seen:
            continue
        seen.add(path)
        found.append(
            {
                "relative_path": path,
                "rank": row.get("rank"),
                "predicted": row.get("predicted"),
                "gold_label": row.get("gold_label"),
                "reference": reference,
                "work_kind": "proof_completion",
            }
        )
    return found


def _punkt(row: dict[str, object] | None) -> str | None:
    if row is None:
        return None
    match = PUNKT_RE.search(str(row.get("text") or ""))
    return None if match is None else match.group(1)


def _c8_group_notes(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    notes = {}
    for run in payload.get("runs") or []:
        groups = (run.get("coverage_groups") or {}).get("groups") or []
        for group in groups:
            notes[str(group.get("relative_path") or "")] = group
    return notes


def _hop_hint(
    path: str, c8_groups: dict[str, dict[str, object]], reference: str | None
) -> dict[str, object] | None:
    group = c8_groups.get(path) or {}
    if any(member.get("neighbor_has_other_span") for member in group.get("members") or []):
        return {"relation": "PREVIOUS_OR_NEXT", "note": group.get("graph_note")}
    if reference:
        return {"relation": f"CLAUSE_{reference}", "note": f"explicit punkt {reference}"}
    return None


def _load_navigate(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item.get("id") or ""): item for item in payload.get("cases") or []}


def _attach_measured_hops(
    ranking: dict[str, object], navigate: dict[str, dict[str, object]]
) -> None:
    measured = {
        "Avtal_46_SaaS_avtal.docx": navigate.get("avtal-46-section") or {},
        "Avtal_49_IT_drift_hostingavtal.docx": navigate.get("avtal-49-punkt-4") or {},
    }
    for row in ranking.get("documents") or []:
        case = measured.get(str(row.get("relative_path") or ""))
        if not case:
            continue
        row["measured_navigation_recall"] = case.get("navigation_recall")
        row["measured_extra_text_units"] = case.get("extra_text_units")
        row["measured_relations"] = case.get("relations_used")
        if case.get("navigation_recall") == 1.0:
            row["hop_possible"] = True
            found = list(case.get("found") or [])
            row["hop_relation"] = (
                (found[0].get("relation") if found else None)
                or (list(case.get("relations_used") or [row.get("hop_relation")])[0])
            )
