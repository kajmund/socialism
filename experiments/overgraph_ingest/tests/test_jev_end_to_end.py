from __future__ import annotations

import json
from pathlib import Path

import pytest

from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.jev_end_to_end import run_jev_end_to_end
from overgraph_ingest.retrieval.jev_property_verify import SUPPORTED, UNSUPPORTED


def _unit(key, path, text, dense, *, document_id="doc", structure_id=""):
    return StoredUnit(1, key, document_id, path, text, dense, None, structure_id=structure_id)


class ScriptedJev:
    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = 0

    def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
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


def _review(tmp_path):
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "gold_id": "confidentiality",
                        "property_class": "confidentiality_obligation",
                        "relative_path": "fp.docx",
                        "polarity": "positive",
                        "value": "true",
                        "evidence": [
                            {
                                "unit_key": "fp1",
                                "unit_text": "Parterna ska samarbeta om sekretess.",
                                "clause_title": "4. Sekretess",
                                "previous_text": "",
                                "next_text": "",
                            }
                        ],
                        "review": {"classification": "wrong_property"},
                    },
                    {
                        "gold_id": "confidentiality",
                        "property_class": "confidentiality_obligation",
                        "relative_path": "gp.docx",
                        "polarity": "positive",
                        "value": "true",
                        "evidence": [
                            {
                                "unit_key": "gp1",
                                "unit_text": "Sekretess nämns i bilagan.",
                                "clause_title": "9. Sekretess",
                                "previous_text": "",
                                "next_text": "",
                            }
                        ],
                        "review": {"classification": "gold_gap"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_end_to_end_stages_and_recovery(tmp_path: Path) -> None:
    units = [
        _unit("gold1", "gold.docx", "Sekretess gäller under avtalstiden.", [1.0, 0.0, 0.0], document_id="d0"),
        _unit("fp1", "fp.docx", "Parterna ska samarbeta om sekretess.", [0.0, 1.0, 0.0], document_id="d1"),
        _unit("gp1", "gp.docx", "Sekretess nämns i bilagan.", [0.0, 1.0, 0.0], document_id="d2"),
        _unit("gp2", "gp.docx", "Part ska iaktta tystnadsplikt om företagshemligheter.", [1.0, 0.0, 0.0], document_id="d2"),
    ]
    structures = {}
    gold = RetrievalGold(
        id="confidentiality",
        query="Vilka avtal innehåller en sekretessplikt?",
        relevant_units=[GoldSpan("gold.docx", "Sekretess gäller")],
        hard_negatives=[],
    )
    cfg = type("Cfg", (), {"db_path": tmp_path / "unused", "dense_dimension": 3, "write_batch_size": 50})()
    fake = ScriptedJev([SUPPORTED, UNSUPPORTED, UNSUPPORTED, UNSUPPORTED, SUPPORTED])
    payload = run_jev_end_to_end(
        cfg,
        review_path=_review(tmp_path),
        units=units,
        structures=structures,
        golds=[gold],
        jev=fake,
        jev_model="fake",
        dense_model="hashed-dense-v1",
        local_k=3,
    ).payload

    metrics = payload["metrics"]
    assert payload["groups"] == {"positive": 1, "error": 1, "gold_gap": 1}
    assert metrics["positive"] == {
        "verified_at_discovery": 1,
        "verified_after_local_dense": 0,
        "not_verified": 0,
    }
    assert metrics["error"] == {
        "verified_at_discovery": 0,
        "verified_after_local_dense": 0,
        "not_verified": 1,
    }
    assert metrics["gold_gap"] == {
        "verified_at_discovery": 0,
        "verified_after_local_dense": 1,
        "not_verified": 0,
    }
    assert metrics["recovery_count"] == 1
    assert metrics["recovery_rate_of_non_supported"] == 0.5
    assert metrics["local_dense_runs"] == 2
    assert metrics["local_dense_skip_rate"] == pytest.approx(1 / 3)
    assert metrics["jev_calls"]["total"] == 5
    assert metrics["jev_calls"]["mean"] == pytest.approx(5 / 3)
    assert payload["manifest"]["second_unsupported_means_not_verified"] is True
