"""Isolated safety gate. Does not change C@8, Coverage v3, or the Jev prompt."""

from __future__ import annotations

import json
import time
from pathlib import Path

from overgraph_ingest.coverage.proof_gate import (
    POLARITY_UNRESOLVED,
    STACKED_POLARITY_CLASS,
    UNDECIDED,
    admit_supported,
    polarity_status,
    reference_integrity,
)
from overgraph_ingest.jev.client import JevClient, JevError
from overgraph_ingest.jev.proof_eval import (
    PROOF_QUESTION,
    evidence_passage,
    parse_proof_choice,
    proof_choice_question,
)

GATE_BASELINE_ID = "phase2-proof-gate-v1"
GATE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{GATE_BASELINE_ID}.json"
)

REFERENCE_CASES = (
    {
        "id": "ref_punkt8_wrong_heading",
        "source": "Begränsningen gäller inte vid överträdelser av punkt 8.",
        "target": "11. Sekretess och personuppgifter",
        "identity_ok": False,
    },
    {
        "id": "ref_punkt8_matching_heading",
        "source": "Begränsningen gäller inte vid överträdelser av punkt 8.",
        "target": "8. Sekretess och tystnadsplikt",
        "identity_ok": True,
    },
    {
        "id": "ref_punkt4_infosec",
        "source": "Ansvarsbegränsningen gäller inte vid brott mot punkt 4.",
        "target": "4. Informationssäkerhet och dataskydd",
        "identity_ok": True,
    },
    {
        "id": "ref_no_pointer_secrecy_heading",
        "source": "Begränsningarna gäller inte vid uppsåt eller grov vårdslöshet.",
        "target": "8. Sekretess",
        "identity_ok": False,
    },
)

POLARITY_PAIRS = (
    {
        "id": "polarity_inte_vid",
        "text": "Begränsningen gäller inte vid sekretessbrott.",
        "expected_jev": "SUPPORTED",
        "gate_polarity": "resolved",
    },
    {
        "id": "polarity_aven_vid",
        "text": "Begränsningen gäller även vid sekretessbrott.",
        "expected_jev": "CONTRADICTED",
        "gate_polarity": "resolved",
    },
    {
        "id": "polarity_inte_utom",
        "text": "Begränsningen gäller inte, utom vid sekretessbrott.",
        "expected_jev": "CONTRADICTED",
        "gate_polarity": "unresolved",
    },
    {
        "id": "polarity_gäller_utom",
        "text": "Begränsningen gäller, utom vid sekretessbrott.",
        "expected_jev": "SUPPORTED",
        "gate_polarity": "resolved",
    },
)


def judge_reference(case: dict[str, object]) -> dict[str, object]:
    integrity = reference_integrity(str(case["source"]), str(case["target"]))
    predicted = "SUPPORTED"
    admitted = admit_supported(
        predicted,
        reference=integrity,
        polarity=polarity_status(str(case["source"])),
    )
    return {
        "id": case["id"],
        "integrity": integrity,
        "admitted": admitted["admitted"],
        "blocked": admitted["blocked"],
        "reason": admitted["reason"],
        "identity_ok": bool(case["identity_ok"]),
        "pass": admitted["blocked"] != bool(case["identity_ok"]),
    }


def judge_polarity(case: dict[str, object], *, predicted: str | None) -> dict[str, object]:
    polarity = polarity_status(str(case["text"]))
    probe = predicted if predicted is not None else "SUPPORTED"
    admitted = admit_supported(probe, polarity=polarity)
    if predicted is None:
        false_complete = polarity == POLARITY_UNRESOLVED and admitted["admitted"] == "SUPPORTED"
    else:
        false_complete = (
            admitted["admitted"] == "SUPPORTED" and case["expected_jev"] != "SUPPORTED"
        )
    return {
        "id": case["id"],
        "text": case["text"],
        "polarity": polarity,
        "expected_jev": case["expected_jev"],
        "predicted_jev": predicted,
        "admitted": admitted["admitted"],
        "blocked": admitted["blocked"],
        "reason": admitted["reason"],
        "gate_polarity_ok": polarity == case["gate_polarity"],
        "false_complete": false_complete,
    }


def run_proof_gate(
    *,
    client: JevClient | None = None,
    model: str = "jev-1.13.0",
    timeout_seconds: float = 8.0,
) -> dict[str, object]:
    references = [judge_reference(case) for case in REFERENCE_CASES]
    polarity_raw: dict[str, str | None] = {}
    started = time.perf_counter()
    if client is not None:
        for case in POLARITY_PAIRS:
            polarity_raw[str(case["id"])] = _ask_polarity(
                client,
                str(case["text"]),
                key=str(case["id"]),
                model=model,
                timeout_seconds=timeout_seconds,
            )
    wall = time.perf_counter() - started
    polarities = [
        judge_polarity(case, predicted=polarity_raw.get(str(case["id"])))
        for case in POLARITY_PAIRS
    ]
    inverted = next(row for row in polarities if row["id"] == "polarity_inte_utom")
    paraphrase = next(row for row in polarities if row["id"] == "polarity_inte_vid")
    stacked = [
        {
            "text": text,
            "polarity": polarity_status(text),
            "blocked": admit_supported("SUPPORTED", polarity=polarity_status(text))["blocked"],
        }
        for text in STACKED_POLARITY_CLASS
    ]
    return {
        "operation": "coverage",
        "experiment": "proof_gate_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "classify_unchanged": True,
        "jev_prompt_unchanged": True,
        "not_an_independent_blind_test": True,
        "proof_jev_rejected_for_standalone": True,
        "proof_gate_applied_to_v3": False,
        "references": references,
        "polarities": polarities,
        "stacked_polarity_class": stacked,
        "reference_pass": all(row["pass"] for row in references),
        "stacked_class_blocked": all(row["blocked"] for row in stacked),
        "false_complete_after_gate": [
            row["id"] for row in polarities if row["false_complete"]
        ],
        "zero_false_complete": not any(row["false_complete"] for row in polarities)
        and all(row["pass"] for row in references)
        and all(row["blocked"] for row in stacked),
        "inverted_exception": {
            "predicted_jev": inverted["predicted_jev"],
            "admitted": inverted["admitted"],
            "blocked": inverted["blocked"],
        },
        "paraphrase_still_admitted": paraphrase["admitted"] == "SUPPORTED"
        and not paraphrase["blocked"],
        "undecided_is_allowed": UNDECIDED,
        "stacked_polarity_is_unresolved": POLARITY_UNRESOLVED,
        "wall_seconds": wall,
        "proof_question": PROOF_QUESTION,
        "jev_model": None if client is None else model,
    }


def freeze_proof_gate_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": GATE_BASELINE_ID,
        "label": (
            "Frozen: reference integrity and polarity gate. "
            "Jev is not a standalone proof evaluator."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "classify_unchanged": True,
        "jev_prompt_unchanged": True,
        "proof_jev_rejected_for_standalone": True,
        "proof_gate_applied_to_v3": False,
        "zero_false_complete": payload.get("zero_false_complete"),
        "headline": {
            "reference_pass": payload.get("reference_pass"),
            "stacked_class_blocked": payload.get("stacked_class_blocked"),
            "false_complete_after_gate": payload.get("false_complete_after_gate"),
            "inverted_exception": payload.get("inverted_exception"),
            "paraphrase_still_admitted": payload.get("paraphrase_still_admitted"),
            "jev_model": payload.get("jev_model"),
        },
        "references": payload.get("references"),
        "polarities": payload.get("polarities"),
        "stacked_polarity_class": payload.get("stacked_polarity_class"),
    }


def write_proof_gate_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or GATE_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_proof_gate_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_proof_gate_baseline(path: Path | None = None) -> dict[str, object]:
    return json.loads((path or GATE_BASELINE_PATH).read_text(encoding="utf-8"))


def _ask_polarity(
    client: JevClient,
    text: str,
    *,
    key: str,
    model: str,
    timeout_seconds: float,
) -> str:
    try:
        result = client.ask(
            state={
                "task": PROOF_QUESTION,
                "judge": "marked_evidence_only",
                "does_not_replace_classify": True,
                "evidence": evidence_passage(text),
            },
            questions={key: proof_choice_question()},
            model=model,
            timeout_seconds=timeout_seconds,
        )
        label, _confidence = parse_proof_choice(result.answers, key)
        return label
    except JevError:
        return "INSUFFICIENT"
