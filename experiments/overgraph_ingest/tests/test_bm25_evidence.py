from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.graph.writer import (
    GraphWriter,
    open_database,
    read_manifest_dimension,
)
from overgraph_ingest.retrieval.evidence_gold import (
    ANSWERABLE,
    NEGATIVE,
    CellEvidenceGold,
    EvidenceAlternative,
    EvidenceGroup,
    ceiling_at,
    covered_groups,
    first_group_ranks,
    inventory_groups,
    load_question_gold,
    required_group_count,
    validate_cell_gold,
    validate_groups_against_units,
)
from overgraph_ingest.retrieval.gold import RetrievalGold, load_gold_suite
from overgraph_ingest.retrieval.index import StoredUnit, load_published_units
from overgraph_ingest.retrieval.search import SearchHit

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "extra-overgraph-phase2"
OVERLAY = ROOT / "retrieval_gold" / "question_gold" / "evidence-groups-v1.json"


def _unit(key: str, path: str, text: str) -> StoredUnit:
    return StoredUnit(1, key, path, path, text, None, None, content_hash=key)


def test_inventory_groups_keep_passage_gold() -> None:
    gold = RetrievalGold(
        id="test",
        query="q",
        relevant_units=[
            type("Span", (), {"relative_path": "a.docx", "contains": "förlängs automatiskt", "reason": ""})(),
            type("Span", (), {"relative_path": "a.docx", "contains": "tolv månader", "reason": ""})(),
        ],
        hard_negatives=[],
    )
    groups = inventory_groups(gold)
    assert len(groups["a.docx"]) == 2
    assert required_group_count(groups) == 2


def test_carveout_requires_two_groups() -> None:
    gold = load_gold_suite(ROOT / "retrieval_gold")[4]
    assert gold.id == "liability-secrecy-carveout"
    groups = inventory_groups(gold)
    assert len(groups["Avtal_46_SaaS_avtal.docx"]) == 2


def test_alternatives_are_not_double_counted() -> None:
    group = EvidenceGroup(
        "g",
        (
            EvidenceAlternative("a.docx", "förlängs automatiskt"),
            EvidenceAlternative("a.docx", "ny period"),
        ),
    )
    hits = [
        SearchHit(1, "u1", 1.0, 1, "d", "a.docx", "Avtalet förlängs automatiskt."),
        SearchHit(2, "u2", 1.0, 2, "d", "a.docx", "En ny period börjar."),
    ]
    assert covered_groups((group,), hits) == {"g"}
    assert first_group_ranks((group,), hits) == {"g": 1}


def test_negative_cell_has_negative_evidence() -> None:
    cells = load_question_gold(OVERLAY)
    cell = next(
        item
        for item in cells
        if item.question_id == "auto-renewal"
        and item.relative_path == "Avtal_15_Bonusavtal.docx"
    )
    assert cell.answerability == NEGATIVE
    assert cell.positive_property is False
    assert cell.groups[0].alternatives[0].contains == "Det förlängs inte automatiskt."


def test_composite_cell_has_two_required_groups() -> None:
    cells = load_question_gold(OVERLAY)
    cell = next(
        item
        for item in cells
        if item.question_id == "liability-secrecy-carveout"
        and item.relative_path == "Avtal_48_Mjukvaruutvecklingsavtal.docx"
    )
    assert cell.answerability == ANSWERABLE
    assert [group.id for group in cell.groups] == ["liability_limitation", "secrecy_carveout"]


def test_not_evaluated_cell_must_not_have_groups() -> None:
    cell = CellEvidenceGold(
        question_id="q",
        relative_path="a.docx",
        split="development",
        answerability="not_evaluated",
        positive_property=None,
        groups=(EvidenceGroup("g", (EvidenceAlternative("a.docx", "text"),)),),
    )
    with pytest.raises(ValueError):
        validate_cell_gold([cell])


def test_missing_evidence_group_mapping_stops_the_run() -> None:
    units = [_unit("u1", "a.docx", "Sekretess gäller.")]
    groups = (EvidenceGroup("g", (EvidenceAlternative("a.docx", "finns inte"),)),)
    with pytest.raises(ValueError):
        validate_groups_against_units(groups, units)


def test_twenty_candidate_ceiling_is_explicit() -> None:
    assert ceiling_at(20, 75) == 20
    assert ceiling_at(20, 7) == 7


@pytest.mark.skipif(not DB.is_dir(), reason="phase-2 database is not present")
def test_overlay_maps_to_real_phase2_units() -> None:
    dimension = read_manifest_dimension(DB) or 3072
    db = open_database(DB, dimension)
    try:
        units = load_published_units(GraphWriter(db, batch_size=500))
    finally:
        db.close()
    cells = load_question_gold(OVERLAY)
    validate_cell_gold(cells, units)
    assert len(cells) == 200
    assert sum(1 for cell in cells if cell.answerability == ANSWERABLE) == 77
    assert sum(1 for cell in cells if cell.answerability == NEGATIVE) == 123
