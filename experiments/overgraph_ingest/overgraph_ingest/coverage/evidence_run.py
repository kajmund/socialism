"""Isolated evidence-proof contract. Does not change C@8 or Coverage v3."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.cache import load_c8_judgments
from overgraph_ingest.coverage.evidence import (
    CLAIM,
    admit_evidence_found,
    build_proof,
    proof_payload,
    validate_span,
)
from overgraph_ingest.coverage.proof_link_run import AVTAL_46_CAP, AVTAL_49, FALSE_COMPLETE_PAIRS
from overgraph_ingest.coverage.v2 import DEFAULT_CACHE
from overgraph_ingest.retrieval.gold import load_retrieval_gold

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_BASELINE_ID = "phase2-proof-evidence-v1"
EVIDENCE_BASELINE_PATH = ROOT / "baselines" / f"{EVIDENCE_BASELINE_ID}.json"
GOLD_PATH = ROOT / "retrieval_gold" / "liability-secrecy-carveout.json"
AVTAL_12 = (
    "avtal-12-b9",
    (
        "B9. Slutreglering\nMed fullgörandet av denna överenskommelse har parterna "
        "inga ytterligare anspråk på varandra med anledning av anställningen eller "
        "dess upphörande. Undantag gäller för pensionsförmåner, ansvar enligt lagen "
        "om företagshemligheter och fel i slutlöneberäkningen.\n"
    ),
    "avtal-12-b8",
    (
        "B8. Frivillighet och betänketid\nArbetstagaren bekräftar att överenskommelsen "
        "har ingåtts frivilligt och att Arbetstagaren har haft möjlighet att rådgöra "
        "med facklig företrädare eller jurist. Arbetstagaren har fått minst [en vecka] "
        "betänketid.\n"
    ),
)
AVTAL_60_HOP = (
    "avtal-60-pub",
    "10.2 DevBrains är personuppgiftsbiträde för de personuppgifter som behandlas i Tjänsten. Ett personuppgiftsbiträdesavtal (Bilaga 1) gäller.\n",
)
FABRICATED = "Ansvarsbegränsningen gäller inte vid brott mot sekretess."


def run_proof_evidence(*, gold_path: Path | None = None) -> dict[str, object]:
    gold = load_retrieval_gold(gold_path or GOLD_PATH)
    c8_path = ROOT / DEFAULT_CACHE[gold.id]
    c8 = (
        load_c8_judgments(json.loads(c8_path.read_text(encoding="utf-8")))
        if c8_path.is_file()
        else []
    )
    positives = [_positive(span.relative_path, span.contains, c8) for span in gold.relevant_units]
    avtal_60_span = next(span for span in gold.relevant_units if span.relative_path.startswith("Avtal_60"))
    avtal_60 = next(row for row in positives if row["id"].startswith("Avtal_60"))
    hop_60 = build_proof(
        [(avtal_60["unit_id"], avtal_60_span.contains)],
        hops=[(avtal_60["unit_id"], avtal_60_span.contains, *AVTAL_60_HOP)],
    )
    avtal_46 = next(span.contains for span in gold.relevant_units if span.relative_path.startswith("Avtal_46"))
    split_46 = build_proof([("avtal-46-cap", AVTAL_46_CAP), ("avtal-46-carve", avtal_46)])
    hop_12 = build_proof(
        [(AVTAL_12[0], AVTAL_12[1])],
        hops=[(AVTAL_12[0], AVTAL_12[1], AVTAL_12[2], AVTAL_12[3])],
    )
    hop_49 = build_proof(
        [("avtal-49-src", AVTAL_49[0])],
        hops=[("avtal-49-src", AVTAL_49[0], "avtal-49-tgt", AVTAL_49[1])],
    )
    controls = [_control(path, source, target) for path, source, target in FALSE_COMPLETE_PAIRS]
    fabricated = validate_span("avtal-60", avtal_60_span.contains, FABRICATED)
    heading = validate_span("heading", "8. Sekretess", "8. Sekretess")
    heading_proof = build_proof([("heading", "8. Sekretess")])
    found = [row["id"] for row in positives if row["evidence_found"]]
    false_found = [row["id"] for row in controls if row["evidence_found"]]
    if hop_12.status == "SUPPORTED":
        false_found.append("Avtal_12")
    return {
        "operation": "coverage",
        "experiment": "proof_evidence_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_jev": True,
        "no_new_controller": True,
        "claim": CLAIM,
        "jev_yes_is_not_proof": True,
        "hop_is_not_proof": True,
        "positives": positives,
        "avtal_60_with_irrelevant_hop": {
            **proof_payload(hop_60),
            "hop_does_not_create_the_span": hop_60.spans[0].unit_id == avtal_60["unit_id"],
        },
        "avtal_46_split": {
            **proof_payload(split_46),
            "span_unit": None if not split_46.spans else split_46.spans[0].unit_id,
        },
        "avtal_12": proof_payload(hop_12),
        "avtal_49": proof_payload(hop_49),
        "controls": controls,
        "fabricated_span_rejected": not fabricated.validated,
        "heading_alone_is_not_proof": not admit_evidence_found(heading_proof) and heading.validated,
        "positives_found": found,
        "positives_expected": [span.relative_path for span in gold.relevant_units],
        "false_found": false_found,
        "zero_false_complete": not false_found,
        "all_positives_found": found == [span.relative_path for span in gold.relevant_units],
        "undecided_kept": (
            hop_12.status == "UNDECIDED"
            and hop_49.status == "UNDECIDED"
            and all(row["status"] == "UNDECIDED" for row in controls)
        ),
    }


def freeze_proof_evidence_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": EVIDENCE_BASELINE_ID,
        "label": (
            "Frozen: EVIDENCE_FOUND requires a source-grounded proof object. "
            "Not the default controller."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_jev": True,
        "no_new_controller": True,
        "zero_false_complete": payload.get("zero_false_complete"),
        "headline": {
            "all_positives_found": payload.get("all_positives_found"),
            "false_found": payload.get("false_found"),
            "fabricated_span_rejected": payload.get("fabricated_span_rejected"),
            "heading_alone_is_not_proof": payload.get("heading_alone_is_not_proof"),
            "undecided_kept": payload.get("undecided_kept"),
            "avtal_12_found": (payload.get("avtal_12") or {}).get("evidence_found"),
            "avtal_49_found": (payload.get("avtal_49") or {}).get("evidence_found"),
            "avtal_60_found_without_hop": (payload.get("avtal_60_with_irrelevant_hop") or {}).get(
                "evidence_found"
            ),
        },
        "positives": payload.get("positives"),
        "avtal_12": payload.get("avtal_12"),
        "avtal_49": payload.get("avtal_49"),
        "avtal_46_split": payload.get("avtal_46_split"),
        "avtal_60_with_irrelevant_hop": payload.get("avtal_60_with_irrelevant_hop"),
        "controls": payload.get("controls"),
    }


def write_proof_evidence_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or EVIDENCE_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_proof_evidence_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_proof_evidence_baseline(path: Path | None = None) -> dict[str, object]:
    return json.loads((path or EVIDENCE_BASELINE_PATH).read_text(encoding="utf-8"))


def _positive(path: str, snippet: str, c8: list[dict[str, object]]) -> dict[str, object]:
    row = next((item for item in c8 if item.get("relative_path") == path and item.get("predicted") == "YES"), None)
    source = snippet if row is None else str(row.get("text") or snippet)
    if snippet not in source:
        source = snippet
    unit_id = path if row is None else str(row.get("key") or path)
    proof = build_proof([(unit_id, source)])
    return {
        "id": path,
        "role": "gold_positive",
        "unit_id": unit_id,
        **proof_payload(proof),
    }


def _control(path: str, source: str, target: str) -> dict[str, object]:
    proof = build_proof([(f"{path}:src", source)], hops=[(f"{path}:src", source, f"{path}:tgt", target)])
    return {"id": path, "role": "false_complete_pair", **proof_payload(proof)}
