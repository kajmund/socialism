from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.jev_property_verify import (
    SUPPORTED,
    UNDECIDED,
    UNSUPPORTED,
    build_positive_controls,
    build_review_controls,
    load_gold_mapping,
    load_taxonomy,
    run_jev_property_verification,
    verify_case,
)


def _unit(key: str, path: str, text: str, *, document_id: str = "doc", structure_id: str = "") -> StoredUnit:
    return StoredUnit(1, key, document_id, path, text, None, None, content_hash=key, structure_id=structure_id)


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


def _review_file(tmp_path: Path, classification: str) -> Path:
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
                        "review": {"classification": classification},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _cfg(tmp_path: Path):
    return type("Cfg", (), {"db_path": tmp_path / "unused", "dense_dimension": 8, "write_batch_size": 50})()


def _units_and_gold():
    units = [
        _unit("gold1", "gold.docx", "Sekretess gäller under avtalstiden.", document_id="doc1"),
        _unit("fp1", "fp.docx", "Parterna ska samarbeta om sekretess.", document_id="doc2", structure_id="s0"),
    ]
    structures = {"s0": {"title": "4. Sekretess", "document_id": "doc2"}}
    gold = RetrievalGold(
        id="confidentiality",
        query="Vilka avtal innehåller en sekretessplikt?",
        relevant_units=[GoldSpan("gold.docx", "Sekretess gäller")],
        hard_negatives=[],
    )
    return units, structures, gold


def test_controls_built_from_gold_and_review(tmp_path: Path) -> None:
    units, _structures, gold = _units_and_gold()
    mapping = load_gold_mapping()
    by_key = {unit.key: unit for unit in units}
    positives = build_positive_controls(units, [gold], mapping, by_key=by_key)
    assert len(positives) == 1
    assert positives[0].relative_path == "gold.docx"
    errors, gaps = build_review_controls(_review_file(tmp_path, "wrong_property"))
    assert len(errors) == 1 and len(gaps) == 0
    errors, gaps = build_review_controls(_review_file(tmp_path, "gold_gap"))
    assert len(errors) == 0 and len(gaps) == 1


def test_ungrounded_supported_is_not_supported(tmp_path: Path) -> None:
    units, _structures, gold = _units_and_gold()
    taxonomy = load_taxonomy()
    by_key = {unit.key: unit for unit in units}
    case = build_positive_controls(units, [gold], load_gold_mapping(), by_key=by_key)[0]
    class UngroundedJev:
        def ask(self, *, state, questions, model, timeout_seconds):
            return JevResult(
                answers={"verdict": {"choice": SUPPORTED}, "source": {"choice": "none"}},
                model=model,
                latency_ms=1.0,
                usage=JevUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
                raw={},
            )

    outcome = verify_case(UngroundedJev(), case, taxonomy, units, model="fake", timeout_seconds=1.0)
    assert outcome.verdict == SUPPORTED
    assert outcome.effective == UNDECIDED  # source "none" -> not grounded
    assert outcome.source_valid is False


def test_run_reports_keep_and_reject_rates(tmp_path: Path) -> None:
    units, structures, gold = _units_and_gold()
    review = _review_file(tmp_path, "wrong_property")
    # two verdicts: positive -> SUPPORTED, error -> UNSUPPORTED
    fake = ScriptedJev([SUPPORTED, UNSUPPORTED])
    payload = run_jev_property_verification(
        _cfg(tmp_path),
        review_path=review,
        units=units,
        structures=structures,
        golds=[gold],
        jev=fake,
        jev_model="fake",
    ).payload
    metrics = payload["metrics"]
    assert payload["groups"] == {"positive": 1, "error": 1, "gold_gap": 0}
    assert metrics["keep_rate_strict"] == 1.0
    assert metrics["keep_rate_cautious"] == 1.0
    assert metrics["reject_rate_errors"] == 1.0
    assert metrics["error_miss_rate"] == 0.0
    assert payload["decision"]["conservative"] is True
    assert payload["manifest"]["undecided_is_not_unsupported"] is True
