from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.jev_property_verify import SUPPORTED, UNSUPPORTED
from overgraph_ingest.retrieval.jev_validation_v1 import run_jev_validation


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


def _review_file(tmp_path: Path) -> Path:
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
                                "unit_key": "f1",
                                "unit_text": "Parterna ska samarbeta om sekretess.",
                                "clause_title": "4. Sekretess",
                                "previous_text": "",
                                "next_text": "",
                            }
                        ],
                        "review": {"classification": None},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _prelim_file(tmp_path: Path) -> Path:
    path = tmp_path / "prelim.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "relative_path": "fp.docx",
                        "property_class": "confidentiality_obligation",
                        "review": {"classification": "wrong_property"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_validation_reports_recall_and_agreement(tmp_path: Path) -> None:
    units = [
        _unit("g1", "gold.docx", "Sekretess gäller under avtalstiden.", [1.0, 0.0, 0.0], "d0"),
        _unit("f1", "fp.docx", "Parterna ska samarbeta om sekretess.", [0.0, 1.0, 0.0], "d1"),
    ]
    gold = RetrievalGold(
        id="confidentiality",
        query="Vilka avtal innehåller en sekretessplikt?",
        relevant_units=[GoldSpan("gold.docx", "Sekretess gäller")],
        hard_negatives=[],
    )
    cfg = type("Cfg", (), {"db_path": tmp_path / "unused", "dense_dimension": 3, "write_batch_size": 50})()
    fake = ScriptedJev([SUPPORTED, UNSUPPORTED, UNSUPPORTED])
    payload = run_jev_validation(
        cfg,
        review_path=_review_file(tmp_path),
        prelim_path=_prelim_file(tmp_path),
        units=units,
        structures={},
        golds=[gold],
        jev=fake,
        jev_model="fake",
        dense_model="hashed-dense-v1",
        local_k=5,
    ).payload

    assert payload["groups"] == {"positive": 1, "suspected_fp": 1}
    totals = payload["metrics"]["totals"]
    assert totals["positive"]["SUPPORTED"] == 1
    assert totals["suspected_fp"]["UNSUPPORTED"] == 1
    assert payload["metrics"]["recall_loss"]["total"] == 0
    assert payload["metrics"]["preliminary_agreement_30"]["wrong_property"]["not_supported"] == 1
    assert payload["manifest"]["preliminary_labels_are_not_gold"] is True
