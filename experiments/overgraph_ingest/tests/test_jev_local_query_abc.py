from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.jev_local_query_abc import run_jev_local_query_abc
from overgraph_ingest.retrieval.jev_property_verify import SUPPORTED


def _unit(key, path, text, dense, document_id="doc"):
    return StoredUnit(1, key, document_id, path, text, dense, None)


class ScriptedJev:
    def __init__(self, verdicts):
        self.verdicts = list(verdicts)

    def ask(self, *, state, questions, model, timeout_seconds):
        verdict = self.verdicts.pop(0)
        source = "none"
        if verdict == SUPPORTED:
            source = next((key for key in questions["source"]["criteria"] if key != "none"), "none")
        return JevResult(
            answers={"verdict": {"choice": verdict}, "source": {"choice": source}},
            model=model,
            latency_ms=1.0,
            usage=JevUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
            raw={},
        )


def _baseline_file(tmp_path: Path) -> Path:
    baseline = {
        "outcomes": [
            {
                "case": {
                    "group": "positive",
                    "gold_id": "confidentiality",
                    "property_class": "confidentiality_obligation",
                    "relative_path": "doc.docx",
                    "polarity": "positive",
                    "value": "true",
                    "unit_key": "u2",
                    "unit_text": "Ingen sekretess här.",
                    "clause_title": "9. Övrigt",
                    "previous_text": "",
                    "next_text": "",
                    "review_classification": None,
                },
                "stage1": "UNSUPPORTED",
                "stage": "not_verified",
            }
        ]
    }
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline), encoding="utf-8")
    return path


def test_abc_arms_measure_recall_and_recovery(tmp_path: Path) -> None:
    units = [
        _unit("u1", "doc.docx", "Sekretess gäller under avtalstiden.", [1.0, 0.0, 0.0], "d0"),
        _unit("u2", "doc.docx", "Ingen sekretess här.", [0.0, 1.0, 0.0], "d0"),
    ]
    gold = RetrievalGold(
        id="confidentiality",
        query="Vilka avtal innehåller en sekretessplikt?",
        relevant_units=[GoldSpan("doc.docx", "Sekretess gäller")],
        hard_negatives=[],
    )
    cfg = type("Cfg", (), {"db_path": tmp_path / "unused", "dense_dimension": 3, "write_batch_size": 50})()
    fake = ScriptedJev([SUPPORTED, SUPPORTED, SUPPORTED])  # one not-verified case x three arms
    payload = run_jev_local_query_abc(
        cfg,
        baseline_path=_baseline_file(tmp_path),
        units=units,
        structures={},
        golds=[gold],
        jev=fake,
        jev_model="fake",
        dense_model="hashed-dense-v1",
        local_k=5,
    ).payload

    assert payload["groups"] == {"positive": 1, "error": 0, "gold_gap": 0}
    for arm in ("A", "B", "C"):
        metrics = payload["arms"][arm]
        assert metrics["evidence_recall_5"]["positive_hit"] == 1
        assert metrics["evidence_recall_5"]["not_verified_positive_hit"] == 1
        assert metrics["jev_recovery_5"]["recovered_total"] == 1
        assert metrics["jev_recovery_5"]["not_verified_positive_recovered"] == 1
    # candidate keys are recorded for the presentation-control check
    for arm in ("A", "B", "C"):
        outcome = payload["outcomes"][arm][0]
        assert set(outcome["top5_keys"]) == {"u1"}
        assert "u2" in outcome["jev_candidate_keys"]
        assert "u1" in outcome["jev_candidate_keys"]
