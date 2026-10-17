from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_enrich_baseline,
    load_tabular_enrich_run_baseline,
)
from overgraph_ingest.retrieval.encode import HashedDenseEncoder
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.tabular.enrich import (
    FIRST_RUN,
    LOCAL,
    ORIGINAL,
    STRUCTURE,
    heading_titles,
    search_text,
    search_texts,
    units_by_document,
)
from overgraph_ingest.tabular.enrich_dev import (
    DEV_DOCUMENTS,
    DO_NOT_TUNE_CELLS,
    RESERVED_DOCUMENTS,
    development_cells,
    select_reserved,
    spanned_cells,
)
from overgraph_ingest.tabular.enrich_eval import (
    refuse_enrich_jev,
    review_enrich_protocol,
    write_enrich_protocol_baseline,
)
from overgraph_ingest.tabular.enrich_run import (
    run_tabular_enrich,
    write_enrich_run_baseline,
)
from overgraph_ingest.tabular.gold import SELECTED_DOCUMENTS
from overgraph_ingest.tabular.holdout import (
    EXTRA_CORPUS,
    HOLD_OUT_DOCUMENTS,
    SEEN_OUTSIDE_DIAGNOSTIC,
)
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.user_gold import YES, GoldSpan as UserSpan, UserCellGold
from tests.test_tabular_review import _unit

ROOT = Path(__file__).resolve().parents[1]
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
HOLDOUT_GOLD = ROOT / "baselines" / "phase2-tabular-holdout-gold-v1.json"
PATH = "Avtal_enrich_script.docx"
STRUCTURE_ID = "s-cap"
OTHER_ID = "s-other"
PATH_STRUCT = {
    STRUCTURE_ID: {
        "path": "/0:Avtal om IT-tjänster/1:Ansvarsbegränsning/2:Undantag",
        "title": "Undantag",
    },
    OTHER_ID: {
        "path": "/0:Avtal om IT-tjänster/3:Sekretess",
        "title": "Sekretess",
    },
}


def _units() -> list:
    return [
        _unit(
            "other",
            PATH,
            "Informationen är konfidentiell.",
            structure_id=OTHER_ID,
            sequence=1,
        ),
        _unit(
            "previous",
            PATH,
            "Ansvarsbegränsningen gäller inte vid uppsåt eller grov vårdslöshet.",
            structure_id=STRUCTURE_ID,
            sequence=2,
        ),
        _unit(
            "current",
            PATH,
            "Detsamma gäller vid brott mot tystnadsplikten.",
            structure_id=STRUCTURE_ID,
            sequence=3,
        ),
    ]


def test_heading_path_comes_from_stored_structure() -> None:
    titles = heading_titles(PATH_STRUCT[STRUCTURE_ID])
    assert titles == ("Avtal om IT-tjänster", "Ansvarsbegränsning", "Undantag")


def test_search_is_not_evidence() -> None:
    units = _units()
    current = units[2]
    ordered = units_by_document(units)[current.document_id]
    original = search_text(ORIGINAL, current, structures=PATH_STRUCT, ordered=ordered)
    structured = search_text(STRUCTURE, current, structures=PATH_STRUCT, ordered=ordered)
    local = search_text(LOCAL, current, structures=PATH_STRUCT, ordered=ordered)
    assert original == current.text
    assert structured.startswith("Avtal om IT-tjänster → Ansvarsbegränsning → Undantag")
    assert current.text in structured
    assert "uppsåt eller grov vårdslöshet" in local
    assert "uppsåt eller grov vårdslöshet" not in current.text
    assert "Informationen är konfidentiell" not in local
    texts = search_texts(LOCAL, units, PATH_STRUCT)
    assert "uppsåt" in texts["current"]
    assert "uppsåt" not in units[2].text


def test_reserved_holdout_is_unused() -> None:
    if EXTRA_CORPUS.is_dir():
        assert select_reserved() == RESERVED_DOCUMENTS
    assert len(RESERVED_DOCUMENTS) == 20
    assert set(RESERVED_DOCUMENTS).isdisjoint(SELECTED_DOCUMENTS)
    assert set(RESERVED_DOCUMENTS).isdisjoint(HOLD_OUT_DOCUMENTS)
    assert set(RESERVED_DOCUMENTS).isdisjoint(SEEN_OUTSIDE_DIAGNOSTIC)
    assert set(DEV_DOCUMENTS) == set(SELECTED_DOCUMENTS) | set(HOLD_OUT_DOCUMENTS)
    assert {path for path, _question in DO_NOT_TUNE_CELLS} <= set(HOLD_OUT_DOCUMENTS)
    assert len(spanned_cells()) == 84


def test_protocol_does_not_run_models() -> None:
    payload = review_enrich_protocol()
    assert payload["does_not_run_jev"] is True
    assert payload["search_is_not_evidence"] is True
    assert payload["hypothesis_2_not_built"] is True
    assert payload["do_not_tune_known_misses"] is True
    assert payload["first_run"] == list(FIRST_RUN)
    assert payload["specified_not_run"] == [LOCAL]
    assert payload["headline"]["jev_not_run"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
    with pytest.raises(RuntimeError, match="retrieval-only"):
        refuse_enrich_jev()
    assert RETRIEVAL_CONCLUSIONS["tabular_enrich"] == "protocol_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_enrich_jev_not_run"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_enrich_c_not_run"] is True
    assert RETRIEVAL_CONCLUSIONS["search_is_not_evidence"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_enrich_hypothesis_2_not_built"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_tune_structure_to_known_misses"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_default_remains_d"] is True


def test_dense_run_scores_evidence_not_search_text() -> None:
    gold = UserCellGold(
        PATH,
        "confidentiality",
        YES,
        (UserSpan("tystnadsplikten"),),
    )
    retrieval = RetrievalGold(
        id="confidentiality",
        query="Finns det en sekretessplikt i avtalet?",
        relevant_units=[],
        hard_negatives=[GoldSpan(PATH, "uppsåt eller grov vårdslöshet")],
    )
    payload = run_tabular_enrich(
        units=_units(),
        structures=PATH_STRUCT,
        dense=HashedDenseEncoder(8),
        documents=(PATH,),
        cells=(gold,),
        retrieval_golds={"confidentiality": retrieval},
    )
    assert payload["does_not_run_jev"] is True
    assert payload["search_is_not_evidence"] is True
    assert payload["hypothesis_2_not_built"] is True
    assert set(payload["variants"]) == {ORIGINAL, STRUCTURE}
    for name in FIRST_RUN:
        row = payload["scored"][name][0]
        assert row["gold_units"] == 1
        assert row["hit@5"] is True
        assert "current" in row["top5_keys"]
        assert row["hard_negative@5"] >= 0
        assert all("Detsamma gäller" in text or "Ansvarsbegränsningen" in text or "konfidentiell" in text for text in row["top5_evidence"])


def test_protocol_baseline_is_write_once(tmp_path: Path) -> None:
    before_c8 = C8.read_bytes()
    before_gold = HOLDOUT_GOLD.read_bytes()
    payload = review_enrich_protocol()
    target = tmp_path / "enrich.json"
    write_enrich_protocol_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_enrich_protocol_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_enrich_protocol_baseline(payload, C8)
    run_payload = run_tabular_enrich(
        units=_units(),
        structures=PATH_STRUCT,
        dense=HashedDenseEncoder(8),
        documents=(PATH,),
        cells=(
            UserCellGold(PATH, "confidentiality", YES, (UserSpan("tystnadsplikten"),)),
        ),
        retrieval_golds={
            "confidentiality": RetrievalGold(
                id="confidentiality",
                query="q",
                relevant_units=[],
                hard_negatives=[],
            )
        },
    )
    run_target = tmp_path / "enrich-run.json"
    write_enrich_run_baseline(run_payload, run_target)
    with pytest.raises(FileExistsError):
        write_enrich_run_baseline(run_payload, run_target)
    assert C8.read_bytes() == before_c8
    assert HOLDOUT_GOLD.read_bytes() == before_gold
    assert len(development_cells()) == 200


def test_frozen_enrich_protocol() -> None:
    frozen = load_tabular_enrich_baseline()
    assert frozen["id"] == "phase2-tabular-enrich-v1"
    assert frozen["does_not_run_jev"] is True
    assert frozen["search_is_not_evidence"] is True
    assert frozen["hypothesis_2_not_built"] is True
    assert frozen["do_not_tune_known_misses"] is True
    assert frozen["first_run"] == ["A", "B"]
    assert frozen["specified_not_run"] == ["C"]
    assert len(frozen["reserved_documents"]) == 20
    assert len(frozen["development_documents"]) == 40
    assert frozen["headline"]["spanned_cells"] == 84
    assert frozen["default_remains_d"] is True


def test_frozen_enrich_run_did_not_beat_a_at_k5() -> None:
    frozen = load_tabular_enrich_run_baseline()
    assert frozen["id"] == "phase2-tabular-enrich-run-v1"
    assert frozen["does_not_run_jev"] is True
    assert frozen["search_is_not_evidence"] is True
    assert frozen["hypothesis_2_not_built"] is True
    assert frozen["default_remains_d"] is True
    assert frozen["headline"]["A"]["gold_hits_at_5"] == 81
    assert frozen["headline"]["B"]["gold_hits_at_5"] == 81
    assert frozen["headline"]["A"]["hit@5"] == frozen["headline"]["B"]["hit@5"]
    assert frozen["headline"]["B"]["hard_negative@5"] == frozen["headline"]["A"]["hard_negative@5"]
    assert frozen["decision"]["do_not_run_c_automatically"] is True
    assert frozen["decision"]["do_not_run_jev"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_enrich_run"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_enrich_b_did_not_beat_a_at_k5"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_enrich_b_rejected"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_original_embeddings_stay"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_run_c_automatically"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_enrich_jev_not_run"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
