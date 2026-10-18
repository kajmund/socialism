"""Isolated linked-relation detector. Does not change Coverage v3."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.proof_link import (
    LINKED_RELATION,
    evaluate_passage,
    evaluate_passages,
    resolve_reference,
)
from overgraph_ingest.retrieval.gold import load_retrieval_gold

ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = ROOT / "retrieval_gold" / "liability-secrecy-carveout.json"
KEYWORD_PAIR = (
    "Begränsningarna gäller inte vid uppsåt eller grov vårdslöshet.",
    "8. Sekretess",
)
FALSE_COMPLETE_PAIRS = (
    (
        "Avtal_37_Allmanna_villkor_B2B.docx",
        "Begränsningarna gäller inte vid uppsåt eller grov vårdslöshet.",
        "8. Sekretess",
    ),
    (
        "Avtal_47_Programvarulicensavtal.docx",
        "utom vid uppsåt, grov vårdslöshet eller ansvar enligt punkt 8.",
        "11. Sekretess och personuppgifter",
    ),
    (
        "Avtal_50_Support_underhallsavtal.docx",
        "utom vid uppsåt, grov vårdslöshet eller brott mot personuppgiftsbiträdesavtalet.",
        "8. Personuppgifter och sekretess",
    ),
    (
        "Avtal_77_Redovisningsuppdrag.docx",
        "Ansvaret är begränsat till fem prisbasbelopp per uppdragsår, utom vid uppsåt eller grov vårdslöshet.",
        "8. Sekretess, personuppgifter och arkivering",
    ),
    (
        "Avtal_78_Uppdragsavtal_juridiskt_ombud.docx",
        "Ansvaret är begränsat till beloppet per uppdrag, utom vid uppsåt eller grov vårdslöshet.",
        "8. Sekretess och personuppgifter",
    ),
)
AVTAL_46_CAP = (
    "DevBrains sammanlagda ansvar per avtalsår är begränsat till de avgifter "
    "som Kunden har betalat under de senaste tolv (12) månaderna."
)
AVTAL_49 = (
    "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot punkt 4.",
    "4. Informationssäkerhet och dataskydd",
)


def run_proof_link(*, gold_path: Path | None = None) -> dict[str, object]:
    gold = load_retrieval_gold(gold_path or GOLD_PATH)
    positives = []
    for span in gold.relevant_units:
        judged = evaluate_passage(span.contains)
        positives.append(
            {
                "relative_path": span.relative_path,
                "role": "gold_positive",
                "status": judged["status"],
                "linked_span": judged["linked_span"],
                "reference": judged["reference"],
            }
        )
    controls = []
    for path, source, target in FALSE_COMPLETE_PAIRS:
        judged = evaluate_passages([source, target])
        resolved = resolve_reference(source, target)
        controls.append(
            {
                "relative_path": path,
                "role": "false_complete_pair",
                "status": judged["status"],
                "cooccurrence_only": judged["cooccurrence_only"],
                "resolved_status": resolved["status"],
                "referent_matches": resolved["referent_matches"],
            }
        )
    regression = evaluate_passages(list(KEYWORD_PAIR))
    carveout_46 = next(
        span.contains for span in gold.relevant_units if span.relative_path.startswith("Avtal_46")
    )
    split = evaluate_passages([AVTAL_46_CAP, carveout_46])
    hop = resolve_reference(*AVTAL_49)
    linked = [row["relative_path"] for row in positives if row["status"] == LINKED_RELATION]
    false_linked = [
        row["relative_path"]
        for row in controls
        if row["status"] == LINKED_RELATION or row["resolved_status"] == LINKED_RELATION
    ]
    ready = (
        len(linked) == len(positives)
        and not false_linked
        and regression["status"] != LINKED_RELATION
        and regression["cooccurrence_only"] is True
        and hop["status"] != LINKED_RELATION
    )
    return {
        "operation": "coverage",
        "experiment": "proof_link_v1",
        "coverage_v3_unchanged": True,
        "does_not_replace_c8": True,
        "no_new_controller": True,
        "proof_link_applied_to_v3": False,
        "rule_b_rejected": True,
        "cooccurrence_is_not_a_relation": True,
        "relation_requires_source_span": True,
        "gold_id": gold.id,
        "positives": positives,
        "controls": controls,
        "cooccurrence_regression": {
            "texts": list(KEYWORD_PAIR),
            "status": regression["status"],
            "cooccurrence_only": regression["cooccurrence_only"],
        },
        "avtal_46_split": {
            "status": split["status"],
            "grounding_is_carveout_sentence": bool(split.get("linked_span")),
            "coverage_group_is_not_the_relation": True,
        },
        "avtal_49_resolved": {
            "status": hop["status"],
            "referent_matches": hop["referent_matches"],
            "resolved": hop["resolved"],
        },
        "linked_positives": linked,
        "positives_expected": len(positives),
        "false_linked": false_linked,
        "false_linked_count": len(false_linked),
        "ready_for_coverage_run": ready,
    }


PROOF_LINK_BASELINE_ID = "phase2-proof-link-v1"
PROOF_LINK_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_LINK_BASELINE_ID}.json"
)


def freeze_proof_link_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": PROOF_LINK_BASELINE_ID,
        "label": (
            "Frozen: a legal relation needs a source-grounded link, not "
            "keyword co-occurrence. Not applied to Coverage v3."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_controller": True,
        "proof_link_applied_to_v3": False,
        "rule_b_rejected": True,
        "cooccurrence_is_not_a_relation": True,
        "relation_requires_source_span": True,
        "ready_for_coverage_run": payload.get("ready_for_coverage_run"),
        "headline": {
            "linked_positives": payload.get("linked_positives"),
            "positives_expected": payload.get("positives_expected"),
            "false_linked_count": payload.get("false_linked_count"),
            "false_linked": payload.get("false_linked"),
            "cooccurrence_regression": payload.get("cooccurrence_regression"),
            "avtal_46_split": payload.get("avtal_46_split"),
            "avtal_49_resolved": payload.get("avtal_49_resolved"),
        },
    }


def write_proof_link_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or PROOF_LINK_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(freeze_proof_link_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_proof_link_baseline(path: Path | None = None) -> dict[str, object]:
    return json.loads((path or PROOF_LINK_BASELINE_PATH).read_text(encoding="utf-8"))
