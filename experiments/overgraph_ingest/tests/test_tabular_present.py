from __future__ import annotations

import json
from pathlib import Path

import pytest

from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_enrich_reject_baseline,
    load_tabular_present_baseline,
    load_tabular_present_reject_baseline,
    load_tabular_present_run_baseline,
)
from overgraph_ingest.tabular.contract import ANSWERED
from overgraph_ingest.tabular.enrich_dev import RESERVED_DOCUMENTS, development_cell_map
from overgraph_ingest.tabular.enrich_reject import (
    review_enrich_reject,
    write_enrich_reject_baseline,
)
from overgraph_ingest.tabular.evaluate import FALSE_ANSWER, TRUE_ANSWER
from overgraph_ingest.tabular.jev_io import answer_cell, proposed_spans
from overgraph_ingest.tabular.jev_io import P0_STATUS_INSTRUCTIONS
from overgraph_ingest.tabular.present import source_preview, state_unit, unit_heading
from overgraph_ingest.tabular.present_eval import (
    refuse_present_model_run,
    review_present_protocol,
    write_present_protocol_baseline,
)
from overgraph_ingest.tabular.present_reject import (
    PRESENT_REJECT_PATH,
    refuse_hypothesis_2_from_this_line,
    refuse_more_metadata,
    refuse_reserved_present_holdout,
    review_present_reject,
    write_present_reject_baseline,
)
from overgraph_ingest.tabular.present_run import (
    PRESENT,
    PRESENT_RUN_PATH,
    TEXT,
    decide_present,
    excerpt_in_evidence,
    heading_bindings,
    heading_cited,
    pair_present,
    run_tabular_present,
    write_present_run_baseline,
    write_present_run_table,
)
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.user_gold import SILENT, YES, GoldSpan, UserCellGold
from tests.test_tabular_holdout_run import HoldoutJev
from tests.test_tabular_review import _unit

ROOT = Path(__file__).resolve().parents[1]
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
ENRICH_RUN = ROOT / "baselines" / "phase2-tabular-enrich-run-v1.json"
PATH = "Avtal_present_script.docx"
STRUCTURE_ID = "s-secret"
STRUCTURES = {
    STRUCTURE_ID: {
        "path": "/0:Avgångsvederlag/1:Sekretess",
        "title": "Sekretess",
        "clause_number": "6.3",
    }
}
CONTRACT_TEXT = "Innehållet i detta avtal är konfidentiellt."


class RecordingJev(HoldoutJev):
    def __init__(self) -> None:
        super().__init__()
        self.states: list[dict] = []
        self.questions: list[dict] = []

    def ask(self, *, state, questions, model, timeout_seconds):
        self.states.append(state)
        self.questions.append(questions)
        return super().ask(state=state, questions=questions, model=model, timeout_seconds=timeout_seconds)


def test_heading_uses_stored_clause_and_title() -> None:
    assert unit_heading(STRUCTURES[STRUCTURE_ID]) == "6.3 – Sekretess"
    unit = _unit("u1", PATH, CONTRACT_TEXT, structure_id=STRUCTURE_ID)
    assert source_preview(unit) == CONTRACT_TEXT[:240]
    labeled = source_preview(unit, STRUCTURES[STRUCTURE_ID])
    assert labeled.startswith("6.3 – Sekretess")
    assert CONTRACT_TEXT in labeled
    payload = state_unit(unit, STRUCTURES[STRUCTURE_ID])
    assert payload["text"] == CONTRACT_TEXT
    assert payload["heading"] == "6.3 – Sekretess"


def test_default_answer_cell_does_not_add_headings() -> None:
    unit = _unit("gold", PATH, "Avtalet förlängs automatiskt med tolv månader.")
    jev = RecordingJev()
    status, source, excerpt, _excerpt_id = answer_cell(
        jev,
        user_question="Förlängs avtalet automatiskt?",
        examined=[unit],
        model="jev-latest",
        timeout_seconds=8.0,
    )
    assert status == ANSWERED
    assert source == "gold"
    assert "förlängs automatiskt" in excerpt
    assert jev.states[0]["units"] == [{"id": "gold", "text": unit.text}]
    assert "heading" not in jev.states[0]["units"][0]
    assert jev.questions[0]["source"]["criteria"]["gold"] == unit.text[:240]
    spans = proposed_spans([unit])
    assert all(span["text"] in unit.text or span["text"] == unit.text for span in spans)


def test_presented_answer_cell_keeps_original_excerpts() -> None:
    unit = _unit(
        "gold",
        PATH,
        "Avtalet förlängs automatiskt med tolv månader.",
        structure_id=STRUCTURE_ID,
    )
    jev = RecordingJev()
    status, source, excerpt, _excerpt_id = answer_cell(
        jev,
        user_question="Förlängs avtalet automatiskt?",
        examined=[unit],
        model="jev-latest",
        timeout_seconds=8.0,
        structures=STRUCTURES,
    )
    assert status == ANSWERED
    assert source == "gold"
    assert excerpt in unit.text
    assert jev.states[0]["units"][0]["text"] == unit.text
    assert jev.states[0]["units"][0]["heading"] == "6.3 – Sekretess"
    assert jev.questions[0]["source"]["criteria"]["gold"].startswith("6.3 – Sekretess")
    assert "förlängs automatiskt" in jev.questions[0]["excerpt"]["criteria"][
        next(key for key in jev.questions[0]["excerpt"]["criteria"] if key != "none")
    ]


def test_present_protocol_does_not_run_jev() -> None:
    payload = review_present_protocol()
    assert payload["does_not_run_jev"] is True
    assert payload["does_not_change_retrieval"] is True
    assert payload["same_five_units"] is True
    assert payload["models_not_run"] is True
    assert payload["do_not_run_c"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
    with pytest.raises(RuntimeError, match="not run yet"):
        refuse_present_model_run()
    assert RETRIEVAL_CONCLUSIONS["tabular_enrich_b_rejected"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_original_embeddings_stay"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_next_is_candidate_presentation"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_present"] == "protocol_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_present_models_not_run"] is False
    assert RETRIEVAL_CONCLUSIONS["tabular_present_run"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_present_rejected"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_micro_optimization_paused"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_run_c_automatically"] is True


def test_enrich_reject_keeps_original_embeddings() -> None:
    payload = review_enrich_reject()
    assert payload["verdict"] == "rejected"
    assert payload["rejected"] == "B"
    assert payload["kept"] == "A"
    assert payload["does_not_run_c"] is True
    assert payload["original_embeddings_stay"] is True
    assert payload["next_is_candidate_presentation"] is True
    assert payload["headline"]["gold_hits_at_5"] == 81


def test_present_and_reject_baselines_are_write_once(tmp_path: Path) -> None:
    before_c8 = C8.read_bytes()
    before_run = ENRICH_RUN.read_bytes()
    reject = review_enrich_reject()
    present = review_present_protocol()
    write_enrich_reject_baseline(reject, tmp_path / "reject.json")
    write_present_protocol_baseline(present, tmp_path / "present.json")
    present_reject = review_present_reject()
    write_present_reject_baseline(present_reject, tmp_path / "present-reject.json")
    with pytest.raises(FileExistsError):
        write_enrich_reject_baseline(reject, tmp_path / "reject.json")
    with pytest.raises(FileExistsError):
        write_present_protocol_baseline(present, tmp_path / "present.json")
    with pytest.raises(FileExistsError):
        write_present_reject_baseline(present_reject, tmp_path / "present-reject.json")
    with pytest.raises(FileExistsError):
        write_enrich_reject_baseline(reject, C8)
    if PRESENT_RUN_PATH.exists():
        before_present_run = PRESENT_RUN_PATH.read_bytes()
        with pytest.raises(FileExistsError):
            write_present_run_baseline(present_reject, PRESENT_RUN_PATH)
        assert PRESENT_RUN_PATH.read_bytes() == before_present_run
    if PRESENT_REJECT_PATH.exists():
        before_present_reject = PRESENT_REJECT_PATH.read_bytes()
        with pytest.raises(FileExistsError):
            write_present_reject_baseline(present_reject, PRESENT_REJECT_PATH)
        assert PRESENT_REJECT_PATH.read_bytes() == before_present_reject
    assert C8.read_bytes() == before_c8
    assert ENRICH_RUN.read_bytes() == before_run


def test_frozen_reject_and_present() -> None:
    rejected = load_tabular_enrich_reject_baseline()
    present = load_tabular_present_baseline()
    assert rejected["verdict"] == "rejected"
    assert rejected["rejected"] == "B"
    assert rejected["kept"] == "A"
    assert rejected["original_embeddings_stay"] is True
    assert rejected["next_is_candidate_presentation"] is True
    assert present["models_not_run"] is True
    assert present["same_five_units"] is True
    assert present["does_not_change_retrieval"] is True
    assert present["do_not_run_c"] is True


def test_frozen_present_run_did_not_help() -> None:
    frozen = load_tabular_present_run_baseline()
    assert frozen["id"] == "phase2-tabular-present-run-v1"
    assert frozen["does_not_change_retrieval"] is True
    assert frozen["same_five_units"] is True
    assert frozen["one_jev_call"] is True
    assert frozen["headings_are_not_excerpts"] is True
    assert frozen["reserved_unused"] is True
    assert frozen["default_remains_d"] is True
    assert frozen["heading_cited"] == 0
    assert frozen["excerpt_outside_evidence"] == 0
    assert frozen["jev_calls"] == 400
    assert frozen["paired"]["changed"] == 8
    assert frozen["paired"]["lost_positive"] == 1
    assert frozen["paired"]["new_false_positive"] == 0
    assert frozen["paired"]["fixed_false_positive"] == 0
    assert frozen["headline"]["text"]["polarity"]["negative_false_answer"] == 12
    assert frozen["headline"]["present"]["polarity"]["negative_false_answer"] == 12
    assert frozen["headline"]["text"]["polarity"]["positive_correct"] == 85
    assert frozen["headline"]["present"]["polarity"]["positive_correct"] == 84
    assert frozen["decision"]["fewer_silent_false_and_kept_positives"] is False
    assert frozen["decision"]["do_not_add_more_metadata_fields"] is True
    assert frozen["decision"]["do_not_run_reserved_holdout"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_present_run"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_present_did_not_reduce_silent_false"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_present_lost_positive"] == 1
    assert RETRIEVAL_CONCLUSIONS["tabular_present_changed_cells"] == 8
    assert RETRIEVAL_CONCLUSIONS["do_not_add_more_metadata_fields"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_run_reserved_holdout"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5


def test_present_reject_closes_the_metadata_line() -> None:
    payload = review_present_reject()
    assert payload["verdict"] == "rejected"
    assert payload["rejected"] == PRESENT
    assert payload["kept"] == TEXT
    assert payload["pause_micro_optimization"] is True
    assert payload["next_quality_needs_new_capability"] is True
    assert payload["do_not_start_hypothesis_2_because_cheaper_failed"] is True
    assert payload["does_not_run_reserved_holdout"] is True
    assert payload["do_not_compare_development_to_holdout"] is True
    assert payload["default_remains_d"] is True
    assert payload["e_is_strongest_measured_candidate"] is True
    assert payload["headline"]["silent_false"] == 12
    assert payload["headline"]["lost_positive"] == 1
    assert payload["headline"]["changed"] == 8
    assert payload["headline"]["enrich_hit@5"] == 81
    assert payload["headline"]["holdout_e_full_success"] == 0.89
    with pytest.raises(RuntimeError, match="more metadata"):
        refuse_more_metadata()
    with pytest.raises(RuntimeError, match="reserved holdout"):
        refuse_reserved_present_holdout()
    with pytest.raises(RuntimeError, match="ingest labeling"):
        refuse_hypothesis_2_from_this_line()


def test_present_reject_refuses_a_positive_run() -> None:
    run = load_tabular_present_run_baseline()
    positive = json.loads(json.dumps(run))
    positive["decision"]["fewer_silent_false_and_kept_positives"] = True
    with pytest.raises(ValueError, match="negative quality"):
        review_present_reject(positive)


def test_frozen_present_reject() -> None:
    frozen = load_tabular_present_reject_baseline()
    assert frozen["id"] == "phase2-tabular-present-reject-v1"
    assert frozen["verdict"] == "rejected"
    assert frozen["rejected"] == PRESENT
    assert frozen["kept"] == TEXT
    assert frozen["pause_micro_optimization"] is True
    assert frozen["next_quality_needs_new_capability"] is True
    assert frozen["do_not_start_hypothesis_2_because_cheaper_failed"] is True
    assert frozen["does_not_run_reserved_holdout"] is True
    assert frozen["do_not_compare_development_to_holdout"] is True
    assert frozen["default_remains_d"] is True
    assert frozen["e_is_strongest_measured_candidate"] is True
    assert frozen["headline"]["silent_false"] == 12
    assert frozen["headline"]["lost_positive"] == 1
    assert frozen["headline"]["text_positive_correct"] == 85
    assert frozen["headline"]["present_positive_correct"] == 84
    assert RETRIEVAL_CONCLUSIONS["tabular_present_rejected"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_present_kept"] == "text"
    assert RETRIEVAL_CONCLUSIONS["tabular_structure_to_jev_rejected"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_micro_optimization_paused"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_start_hypothesis_2_because_cheaper_failed"] is True
    assert RETRIEVAL_CONCLUSIONS["next_quality_needs_new_capability"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_compare_development_present_to_holdout"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_e_is_strongest_measured_candidate"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_default_remains_d"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5


SPAN = "Avtalet förlängs automatiskt med tolv månader."
GOLD_STRUCTURE = "s-term"
NOISE_STRUCTURE = "s-secret"
RUN_STRUCTURES = {
    GOLD_STRUCTURE: {
        "path": "/0:Avtal/1:Avtalstid",
        "title": "Avtalstid",
        "clause_number": "9.1",
    },
    NOISE_STRUCTURE: {
        "path": "/0:Avtal/2:Sekretess",
        "title": "Sekretess",
        "clause_number": "6.3",
    },
}


def _run_units() -> list:
    rows = [
        _unit(
            f"noise-{index}",
            PATH,
            "Ingen sekretess.",
            structure_id=NOISE_STRUCTURE,
            sequence=index,
            dense=[0.0, 1.0],
            sparse=[(2, 1.0)],
        )
        for index in range(1, 5)
    ]
    rows.append(
        _unit(
            "gold",
            PATH,
            SPAN,
            structure_id=GOLD_STRUCTURE,
            sequence=5,
            dense=[1.0, 0.0],
            sparse=[(1, 1.0)],
        )
    )
    return rows


def _run_golds() -> dict[tuple[str, str], UserCellGold]:
    return {
        (PATH, "auto-renewal"): UserCellGold(
            PATH,
            "auto-renewal",
            YES,
            (GoldSpan("förlängs automatiskt"),),
        ),
        (PATH, "notice-period"): UserCellGold(PATH, "notice-period", SILENT, ()),
    }


def _run_queries() -> dict[str, tuple[list[float], list[tuple[int, float]]]]:
    encoded = ([1.0, 0.0], [(1, 1.0)])
    return {"auto-renewal": encoded, "notice-period": encoded}


def _run_present(**kwargs):
    return run_tabular_present(
        units=_run_units(),
        structures=RUN_STRUCTURES,
        queries=_run_queries(),
        documents=(PATH,),
        question_ids=("auto-renewal", "notice-period"),
        golds=_run_golds(),
        **kwargs,
    )


def test_heading_binds_to_the_unit_structure() -> None:
    units = _run_units()
    by_key = {unit.key: unit for unit in units}

    class Hit:
        def __init__(self, key: str) -> None:
            self.key = key

    bindings = heading_bindings(
        [Hit("gold"), Hit("noise-1")],
        by_key,
        RUN_STRUCTURES,
    )
    assert bindings["gold"] == {
        "structure_id": GOLD_STRUCTURE,
        "heading": "9.1 – Avtalstid",
    }
    assert bindings["noise-1"] == {
        "structure_id": NOISE_STRUCTURE,
        "heading": "6.3 – Sekretess",
    }


def test_heading_cited_only_when_excerpt_is_constructed_metadata() -> None:
    units = {unit.key: unit for unit in _run_units()}
    headings = {
        "gold": {"structure_id": GOLD_STRUCTURE, "heading": "9.1 – Avtalstid"},
    }
    answered = {
        "status": ANSWERED,
        "sources": [{"unit_id": "gold", "excerpt": SPAN}],
    }
    leaked = {
        "status": ANSWERED,
        "sources": [{"unit_id": "gold", "excerpt": "9.1 – Avtalstid"}],
    }
    assert excerpt_in_evidence(answered, units) is True
    assert heading_cited(answered, headings, units) is False
    assert excerpt_in_evidence(leaked, units) is False
    assert heading_cited(leaked, headings, units) is True


def test_pair_present_counts_changed_cells_and_false_positives() -> None:
    text_rows = [
        {
            "relative_path": PATH,
            "question_id": "auto-renewal",
            "polarity": YES,
            "status": ANSWERED,
            "outcome": TRUE_ANSWER,
            "full_success": True,
        },
        {
            "relative_path": PATH,
            "question_id": "notice-period",
            "polarity": SILENT,
            "status": ANSWERED,
            "outcome": FALSE_ANSWER,
            "full_success": False,
        },
    ]
    present_rows = [
        {
            "relative_path": PATH,
            "question_id": "auto-renewal",
            "polarity": YES,
            "status": ANSWERED,
            "outcome": TRUE_ANSWER,
            "full_success": False,
        },
        {
            "relative_path": PATH,
            "question_id": "notice-period",
            "polarity": SILENT,
            "status": "NOT_FOUND",
            "outcome": "correct_not_found",
            "full_success": True,
        },
    ]
    cells = [
        {
            "variant": TEXT,
            "relative_path": PATH,
            "question_id": "auto-renewal",
            "answer": SPAN,
            "retrieval": {"candidate_keys": ["gold"]},
        },
        {
            "variant": PRESENT,
            "relative_path": PATH,
            "question_id": "auto-renewal",
            "answer": "annat svar",
            "retrieval": {"candidate_keys": ["gold"]},
        },
        {
            "variant": TEXT,
            "relative_path": PATH,
            "question_id": "notice-period",
            "answer": "sekretess",
            "retrieval": {"candidate_keys": ["gold"]},
        },
        {
            "variant": PRESENT,
            "relative_path": PATH,
            "question_id": "notice-period",
            "answer": "",
            "retrieval": {"candidate_keys": ["gold"]},
        },
    ]
    paired = pair_present(text_rows, present_rows, cells)
    assert paired["cells"] == 2
    assert paired["changed"] == 2
    assert paired["lost_positive"] == 1
    assert paired["new_false_positive"] == 0
    assert paired["fixed_false_positive"] == 1


def test_pair_present_refuses_changed_candidates() -> None:
    row = {
        "relative_path": PATH,
        "question_id": "auto-renewal",
        "polarity": YES,
        "status": ANSWERED,
        "outcome": TRUE_ANSWER,
        "full_success": True,
    }
    cells = [
        {
            "variant": TEXT,
            "relative_path": PATH,
            "question_id": "auto-renewal",
            "retrieval": {"candidate_keys": ["gold"]},
        },
        {
            "variant": PRESENT,
            "relative_path": PATH,
            "question_id": "auto-renewal",
            "retrieval": {"candidate_keys": ["other"]},
        },
    ]
    with pytest.raises(ValueError, match="changed retrieval"):
        pair_present([row], [row], cells)


def test_present_run_keeps_the_same_five_units() -> None:
    jev = RecordingJev()
    payload = _run_present(jev=jev)
    assert payload["does_not_change_retrieval"] is True
    assert payload["same_five_units"] is True
    assert payload["one_jev_call"] is True
    assert payload["reserved_unused"] is True
    assert payload["default_remains_d"] is True
    assert payload["heading_cited"] == 0
    assert payload["excerpt_outside_evidence"] == 0
    assert payload["jev_calls"] == 4
    assert jev.calls == 4
    assert len(payload["cells"]) == 4
    text_cells = [cell for cell in payload["cells"] if cell["variant"] == TEXT]
    present_cells = [cell for cell in payload["cells"] if cell["variant"] == PRESENT]
    assert [cell["retrieval"]["candidate_keys"] for cell in text_cells] == [
        cell["retrieval"]["candidate_keys"] for cell in present_cells
    ]
    assert all(len(cell["retrieval"]["candidate_keys"]) == 5 for cell in payload["cells"])
    gold_heading = present_cells[0]["retrieval"]["headings"]["gold"]
    assert gold_heading["structure_id"] == GOLD_STRUCTURE
    assert gold_heading["heading"] == "9.1 – Avtalstid"
    assert present_cells[0]["retrieval"]["headings"]["noise-1"]["heading"] == "6.3 – Sekretess"
    assert "heading" not in jev.states[0]["units"][0]
    gold_state = next(unit for unit in jev.states[1]["units"] if unit["id"] == "gold")
    noise_state = next(unit for unit in jev.states[1]["units"] if unit["id"] == "noise-1")
    assert gold_state["heading"] == "9.1 – Avtalstid"
    assert gold_state["text"] == SPAN
    assert noise_state["heading"] == "6.3 – Sekretess"
    assert jev.questions[1]["source"]["criteria"]["gold"].startswith("9.1 – Avtalstid")
    assert SPAN in jev.questions[1]["source"]["criteria"]["gold"]
    auto = [cell for cell in payload["cells"] if cell["question_id"] == "auto-renewal"]
    assert all(cell["status"] == ANSWERED for cell in auto)
    assert all(cell["excerpt_in_evidence"] is True for cell in auto)
    assert all(cell["answer"] in SPAN for cell in auto)
    assert payload["paired"]["changed"] == 0
    assert payload["paired"]["lost_positive"] == 0
    assert payload["paired"]["new_false_positive"] == 0
    assert payload["decision"]["do_not_add_more_metadata_fields"] is True
    assert payload["decision"]["do_not_run_reserved_holdout"] is True


def test_present_run_does_not_reopen_graph_during_jev(monkeypatch) -> None:
    def boom(**_kwargs):
        raise AssertionError("graph reopened during present")

    monkeypatch.setattr("overgraph_ingest.tabular.present_run._load_context", boom)
    graph = GraphContext(_run_units(), RUN_STRUCTURES, {}, {})
    payload = run_tabular_present(
        context=graph,
        queries=_run_queries(),
        jev=HoldoutJev(),
        documents=(PATH,),
        question_ids=("auto-renewal", "notice-period"),
        golds=_run_golds(),
    )
    assert payload["jev_calls"] == 4


def test_present_run_refuses_reserved_holdout() -> None:
    with pytest.raises(ValueError, match="reserved"):
        run_tabular_present(
            documents=(RESERVED_DOCUMENTS[0],),
            golds={},
            queries={},
            jev=HoldoutJev(),
            context=GraphContext([], {}, {}, {}),
        )


def test_development_gold_excludes_reserved() -> None:
    mapping = development_cell_map()
    assert len(mapping) == 200
    assert not {path for path, _question in mapping} & set(RESERVED_DOCUMENTS)


def test_present_run_baseline_is_write_once(tmp_path: Path) -> None:
    before_c8 = C8.read_bytes()
    before_present = (ROOT / "baselines" / "phase2-tabular-present-v1.json").read_bytes()
    payload = _run_present(jev=HoldoutJev())
    write_present_run_table(payload, tmp_path)
    target = tmp_path / "present-run.json"
    write_present_run_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_present_run_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_present_run_baseline(payload, C8)
    if PRESENT_RUN_PATH.exists():
        with pytest.raises(FileExistsError):
            write_present_run_baseline(payload, PRESENT_RUN_PATH)
    assert C8.read_bytes() == before_c8
    assert (ROOT / "baselines" / "phase2-tabular-present-v1.json").read_bytes() == before_present
    table = (tmp_path / "present-run-v1.md").read_text(encoding="utf-8")
    assert "Changed cells:" in table
    assert "New false positives:" in table
    assert "Lost previously correct positives:" in table


def test_decide_present_requires_fewer_false_and_kept_positives() -> None:
    summaries = {
        TEXT: {
            "polarity": {
                "negative_false_answer": 2,
                "positive_correct": 10,
            }
        },
        PRESENT: {
            "polarity": {
                "negative_false_answer": 1,
                "positive_correct": 10,
            }
        },
    }
    decision = decide_present(summaries, {"changed": 3})
    assert decision["fewer_silent_false_and_kept_positives"] is True
    summaries[PRESENT]["polarity"]["positive_correct"] = 9
    decision = decide_present(summaries, {"changed": 3})
    assert decision["fewer_silent_false_and_kept_positives"] is False
