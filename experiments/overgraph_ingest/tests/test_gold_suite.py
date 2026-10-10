import json
from pathlib import Path

import pytest

from overgraph_ingest.extraction.model import document_from_dict
from overgraph_ingest.jev.baseline import ARCHITECTURE
from overgraph_ingest.retrieval.gold import load_gold_suite, load_retrieval_gold
from overgraph_ingest.segmentation.structural import segment_document

GOLD_DIR = Path(__file__).resolve().parents[1] / "retrieval_gold"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "extra-cache"


def test_architecture_keeps_three_separate_operations() -> None:
    assert ARCHITECTURE["operations"] == ["classify", "navigate", "coverage"]
    assert ARCHITECTURE["operations_are_separate"] is True


def test_gold_suite_lists_measured_and_new_questions() -> None:
    index = json.loads((GOLD_DIR / "index.json").read_text(encoding="utf-8"))
    golds = load_gold_suite(GOLD_DIR)
    assert [item["id"] for item in index["golds"]] == [gold.id for gold in golds]
    assert golds[0].id == "auto-renewal"
    assert {gold.id for gold in golds} == {
        "auto-renewal",
        "notice-period",
        "liability-cap",
        "confidentiality",
        "liability-secrecy-carveout",
    }
    assert golds[0].classify_question
    carveout = next(gold for gold in golds if gold.id == "liability-secrecy-carveout")
    assert carveout.kind == "multi_clause"
    assert carveout.proof_kind == "COMPOSITE"
    assert golds[0].proof_kind == "EXISTS"
    assert carveout.coverage_groups[0].relative_path.startswith("Avtal_46_")
    assert "Avtal_30_Ramavtal_tjanster.docx" in carveout.relevant_documents
    assert "Avtal_36_Underleverantorsavtal.docx" in carveout.relevant_documents
    assert carveout.relevant_documents == carveout.passage_documents
    liability = next(gold for gold in golds if gold.id == "liability-cap")
    assert len(liability.relevant_documents) == 28
    assert len(liability.relevant_units) == 34
    assert liability.relevant_documents == liability.passage_documents
    assert any(span.relative_path.startswith("Avtal_62_") for span in liability.relevant_units)
    assert not any(span.relative_path.startswith("Avtal_61_") for span in liability.relevant_units)


@pytest.mark.skipif(not CACHE_DIR.is_dir(), reason="extra-cache is not present")
def test_gold_suite_spans_exist_in_cached_text_units() -> None:
    by_path = _cached_units()
    missing: list[str] = []
    for gold in load_gold_suite(GOLD_DIR):
        for span in [*gold.relevant_units, *gold.hard_negatives, *gold.watch_negatives]:
            units = by_path.get(span.relative_path, [])
            if not any(span.contains in text for text in units):
                missing.append(f"{gold.id}:{span.relative_path}:{span.contains}")
        for group in gold.coverage_groups:
            units = by_path.get(group.relative_path, [])
            joined = "\n".join(units)
            for snippet in group.contains:
                if snippet not in joined:
                    missing.append(f"{gold.id}:coverage:{group.relative_path}:{snippet}")
    assert missing == []


def test_auto_renewal_gold_is_unchanged() -> None:
    gold = load_retrieval_gold(GOLD_DIR / "auto-renewal.json")
    assert len(gold.relevant_documents) == 20
    assert gold.hard_negatives[0].relative_path.startswith("Avtal_15_")


def _cached_units() -> dict[str, list[str]]:
    units: dict[str, list[str]] = {}
    if not CACHE_DIR.is_dir():
        return units
    for path in CACHE_DIR.glob("*.extract-v1.json"):
        extracted = document_from_dict(json.loads(path.read_text(encoding="utf-8")))
        if extracted.status != "ok":
            continue
        segmented = segment_document(
            extracted,
            document_version_id="gold-suite",
            segmentation_version="structural-v1",
        )
        units[extracted.relative_path] = [unit.text for unit in segmented.units]
    return units
