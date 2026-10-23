"""B3b: candidate recall vs ranking vs Jev decision, four facit categories.

No full arm run. Candidate generation is deterministic; ranking arms are
current/metadata/embedding-proxy; Jev is asked directly about the known facit
pair so decision correctness is separated from selection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.jev.system import HttpJevSystemOne
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.research.sufficiency_experiment.claims import (
    extract_claim_candidates,
)
from app.services.research.sufficiency_experiment.gap_cases import (
    candidate_miss_synonyms,
)
from app.services.research.sufficiency_experiment.golden import all_golden_cases
from app.services.research.sufficiency_experiment.pair_eval import evaluate_pair
from app.services.research.sufficiency_experiment.pairs import select_pairs
from app.services.research.sufficiency_experiment.prioritization import (
    prioritize_pairs,
)
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    ClaimCandidate,
    ExperimentConfig,
    PairCandidate,
)

DEFAULT_OUT = Path("tests/integration/baselines/b3b-stages-v1.json")
GOLD = Path("tests/integration/baselines/pair-gold-v1.json")
BUDGETS = (1, 5, 10, 20, 40)
ARMS = ("current", "metadata", "embedding")
CLEAR = {"duplicate_contradiction", "independent_contradiction", "tail_claim_contradiction"}
SUBTLE = {"late_evidence", "large_567k"}
COMPATIBLE = {"compatible_periods", "compatible_entities"}


def _facit_pair(left: str, right: str) -> PairCandidate:
    return PairCandidate(
        pair_id=f"facit:{left}|{right}",
        need_id="research_1",
        left_claim_id=left,
        right_claim_id=right,
        score=0.0,
        sources=("facit",),
        features=(),
    )


def _marker_claims(claims: tuple[ClaimCandidate, ...]) -> tuple[ClaimCandidate, ClaimCandidate] | None:
    contradiction = next((claim for claim in claims if "MOTBEVIS" in claim.text), None)
    support = next(
        (claim for claim in claims if "Högsta domstolen tillämpar" in claim.text),
        None,
    )
    if contradiction is None or support is None:
        return None
    return support, contradiction


def _load_gold() -> dict:
    entries = json.loads(GOLD.read_text(encoding="utf-8"))["cases"]
    return {entry["case_id"]: entry for entry in entries}


def _claim_context(case, config):
    passages = segment_evidence(case.evidence, max_chars=config.max_passage_chars)
    claims, _ = extract_claim_candidates(
        passages, {item.evidence_id: item for item in case.evidence}, config=config
    )
    return passages, claims, {claim.claim_id: claim for claim in claims}


def _case_entry(case, gold: dict, config):
    if case.case_id in CLEAR | COMPATIBLE:
        entry = gold[case.case_id]
        facit = entry["contradiction_pairs"]
        expected = "contradiction" if facit else "compatible"
        if not facit:
            facit = entry["candidate_pairs"]
        left, right = sorted(facit[0]) if facit else (None, None)
        return expected, _facit_pair(left, right) if left and right else None
    if case.case_id == "candidate_miss_synonyms":
        passages, claims, by_id = _claim_context(case, config)
        support = next((claim for claim in claims if "Hundar" in claim.text), None)
        contradiction = next((claim for claim in claims if "Tamdjur" in claim.text), None)
        if support is None or contradiction is None:
            return "contradiction", None
        return "contradiction", _facit_pair(support.claim_id, contradiction.claim_id)
    if case.case_id in SUBTLE:
        passages, claims, by_id = _claim_context(case, config)
        marker = _marker_claims(claims)
        if marker is None:
            return "contradiction", None
        support, contradiction = marker
        return "contradiction", _facit_pair(support.claim_id, contradiction.claim_id)
    return "contradiction", None


async def _jev_verdict(case, pair, *, passages, claims_by_id, config):
    if pair is None:
        return None
    client = HttpJevSystemOne()
    evidence_by_id = {item.evidence_id: item for item in case.evidence}
    evaluation = await evaluate_pair(
        pair,
        claims=claims_by_id,
        passages={passage.passage_id: passage for passage in passages},
        evidence_by_id=evidence_by_id,
        client=client,
        config=config,
    )
    return {
        "verdict": evaluation.verdict,
        "contradicts": evaluation.verdict == "CONTRADICTS",
        "status": evaluation.status,
        "error": evaluation.error,
    }


async def _measure(out: Path) -> dict:
    config = ExperimentConfig()
    gold = _load_gold()
    cases = {case.case_id: case for case in all_golden_cases()}
    provider = OpenAIEmbeddingProvider.from_settings() if "embedding" in ARMS else None
    rows = []
    extra = {"candidate_miss_synonyms": candidate_miss_synonyms()}
    all_cases = {**cases, **extra}
    for case_id, category in (
        *[(item, "clear") for item in CLEAR],
        *[(item, "subtle") for item in SUBTLE],
        *[(item, "compatible") for item in COMPATIBLE],
        ("candidate_miss_synonyms", "candidate_miss"),
    ):
        case = all_cases[case_id]
        passages, claims, claims_by_id = _claim_context(case, config)
        selection = await select_pairs(
            claims, case.plan.needs, strategy="deterministic", config=config
        )
        expected, facit = _case_entry(case, gold, config)
        facit_key = (
            frozenset((facit.left_claim_id, facit.right_claim_id)) if facit else frozenset()
        )
        candidate_exists = any(
            frozenset((pair.left_claim_id, pair.right_claim_id)) == facit_key
            for pair in selection.candidates
        )
        arm_rows = {}
        for arm in ARMS:
            ranked = await prioritize_pairs(
                selection.candidates,
                claims_by_id,
                ordering=arm,
                embedding_provider=provider,
            )
            rank = next(
                (
                    index
                    for index, pair in enumerate(ranked, start=1)
                    if frozenset((pair.left_claim_id, pair.right_claim_id)) == facit_key
                ),
                None,
            )
            arm_rows[arm] = {
                "rank": rank,
                "recall_at": {
                    str(budget): (rank is not None and rank <= budget)
                    for budget in BUDGETS
                },
            }
        jev = await _jev_verdict(
            case,
            facit,
            passages=passages,
            claims_by_id=claims_by_id,
            config=config,
        )
        jev_correct = None
        if jev is not None:
            detected = bool(jev["contradicts"])
            jev_correct = detected if expected == "contradiction" else not detected
        if facit is None:
            attribution = "facit_unavailable"
        elif not candidate_exists:
            attribution = "candidate_miss"
        elif any(
            arm_rows[arm]["rank"] is None
            or (arm_rows[arm]["rank"] or 41) > config.max_pairs_per_need
            for arm in ARMS
        ):
            attribution = "ranking_beyond_budget"
        elif jev_correct is False:
            attribution = "jev_wrong_verdict"
        else:
            attribution = "none"
        rows.append(
            {
                "case_id": case_id,
                "category": category,
                "expected": expected,
                "facit_pair": (
                    sorted([facit.left_claim_id, facit.right_claim_id]) if facit else None
                ),
                "candidates": len(selection.candidates),
                "facit_available": facit is not None,
                "candidate_recall": candidate_exists,
                "arms": arm_rows,
                "jev_on_facit": jev,
                "jev_decision_correct": jev_correct,
                "attribution": attribution,
            }
        )
    summary = {
        "candidate_recall": {
            row["case_id"]: row["candidate_recall"] for row in rows
        },
        "recall_at_budget": {
            arm: {
                str(budget): round(
                    sum(
                        1
                        for row in rows
                        if row["facit_available"]
                        and row["expected"] == "contradiction"
                        and row["arms"][arm]["recall_at"][str(budget)]
                    )
                    / max(
                        1,
                        sum(
                            1
                            for row in rows
                            if row["facit_available"]
                            and row["expected"] == "contradiction"
                        ),
                    ),
                    3,
                )
                for budget in BUDGETS
            }
            for arm in ARMS
        },
        "recall_at_budget_denominator": sum(
            1
            for row in rows
            if row["facit_available"] and row["expected"] == "contradiction"
        ),
        "jev_decision_accuracy": round(
            sum(1 for row in rows if row["jev_decision_correct"] is True)
            / max(1, sum(1 for row in rows if row["jev_decision_correct"] is not None)),
            3,
        ),
        "attribution": {row["case_id"]: row["attribution"] for row in rows},
    }
    payload = {
        "measurement": "b3b_stages",
        "recorded_at": datetime.now(UTC).isoformat(),
        "note": "Candidate recall, ranking recall and Jev decision are separated. Compatible pairs are excluded from Recall@Budget denominators; final decision quality/coverage is measured separately.",
        "config": asdict(config),
        "embedding_model": provider.model if provider is not None else None,
        "facit_categories": {
            "clear": sorted(CLEAR),
            "subtle": sorted(SUBTLE),
            "compatible": sorted(COMPATIBLE),
            "candidate_miss": "candidate_miss_synonyms",
        },
        "summary": summary,
        "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    for row in rows:
        print(row["case_id"], row["category"], "cand=", row["candidate_recall"], "rank=", {arm: row["arms"][arm]["rank"] for arm in ARMS}, "jev=", row["jev_decision_correct"], row["attribution"])
    print(f"wrote {out}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    asyncio.run(_measure(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
