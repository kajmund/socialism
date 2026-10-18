from __future__ import annotations

from pathlib import Path

import pytest

from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_tabular_multi_run_baseline,
)
from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND
from overgraph_ingest.tabular.enrich_dev import RESERVED_DOCUMENTS
from overgraph_ingest.tabular.jev_io import (
    MULTI_SLOTS,
    P0_STATUS_INSTRUCTIONS,
    SLOT_IDS,
    answer_cell,
    answer_cell_multi,
    proposed_spans,
)
from overgraph_ingest.tabular.multi_eval import (
    multi_cells,
    multi_documents,
    review_multi_protocol,
    score_multi_cell,
)
from overgraph_ingest.tabular.multi_run import (
    MULTI,
    MULTI_RUN_PATH,
    SINGLE,
    run_tabular_multi,
    write_multi_run_baseline,
    write_multi_run_table,
)
from overgraph_ingest.tabular.prompts import PROMPT_P0, instruction_for
from overgraph_ingest.tabular.search import DEFAULT_K
from overgraph_ingest.tabular.user_gold import YES, GoldSpan, UserCellGold
from tests.test_tabular_holdout_run import HoldoutJev
from tests.test_tabular_review import _unit

ROOT = Path(__file__).resolve().parents[1]
C8 = ROOT / "baselines" / "phase2-jev-classify-c8.json"
PRESENT_REJECT = ROOT / "baselines" / "phase2-tabular-present-reject-v1.json"
PATH = "Avtal_multi_script.docx"
NOTICE = (
    "Uppsägningstiden är tre månader för båda parter. "
    "Under provanställning är den 14 dagar."
)
AUTO = "Avtalet förlängs automatiskt med tolv månader."


class MultiScriptJev(HoldoutJev):
    def __init__(self, extra: str | None = None) -> None:
        super().__init__()
        self.extra = extra
        self.question_keys: list[tuple[str, ...]] = []

    def ask(self, *, state, questions, model, timeout_seconds):
        self.question_keys.append(tuple(questions))
        if "answer_1" not in questions:
            return super().ask(
                state=state,
                questions=questions,
                model=model,
                timeout_seconds=timeout_seconds,
            )
        self.calls += 1
        self.kinds.append("multi")
        criteria = questions["answer_1"]["criteria"]
        question = str(state.get("question") or "")
        if "automatiskt" in question:
            needles = ["förlängs automatiskt"]
        else:
            needles = ["tre månader", "14 dagar"]
        if self.extra:
            needles.append(self.extra)
        picks = [
            key
            for key, text in criteria.items()
            if key != "none" and any(needle in text for needle in needles)
        ]
        answers = {
            "status": {"choice": ANSWERED if picks else NOT_FOUND},
        }
        for index, slot in enumerate(SLOT_IDS):
            answers[slot] = {"choice": picks[index] if index < len(picks) else "none"}
        return JevResult(
            answers=answers,
            model="jev-latest",
            latency_ms=1.0,
            usage=JevUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
            raw={"answers": answers},
        )


def _units() -> list:
    rows = [
        _unit(
            f"noise-{index}",
            PATH,
            "Ingen sekretess.",
            sequence=index,
            dense=[0.0, 1.0],
            sparse=[(2, 1.0)],
        )
        for index in range(1, 4)
    ]
    rows.append(
        _unit("notice", PATH, NOTICE, sequence=4, dense=[1.0, 0.0], sparse=[(1, 1.0)])
    )
    rows.append(
        _unit("auto", PATH, AUTO, sequence=5, dense=[1.0, 0.0], sparse=[(1, 1.0)])
    )
    return rows


def _golds() -> dict[tuple[str, str], UserCellGold]:
    return {
        (PATH, "auto-renewal"): UserCellGold(
            PATH,
            "auto-renewal",
            YES,
            (GoldSpan("förlängs automatiskt"),),
        ),
        (PATH, "notice-period"): UserCellGold(
            PATH,
            "notice-period",
            YES,
            (GoldSpan("tre månader", "ordinarie"), GoldSpan("14 dagar", "provanställning")),
        ),
    }


def _queries() -> dict[str, tuple[list[float], list[tuple[int, float]]]]:
    encoded = ([1.0, 0.0], [(1, 1.0)])
    return {"auto-renewal": encoded, "notice-period": encoded}


def test_multi_protocol_keeps_one_call_and_same_units() -> None:
    payload = review_multi_protocol()
    assert payload["same_five_units"] is True
    assert payload["one_jev_call"] is True
    assert payload["does_not_change_retrieval"] is True
    assert payload["does_not_run_reserved_holdout"] is True
    assert payload["do_not_start_product_from_this_run"] is True
    assert payload["slots"] == 5
    assert payload["multi_cells"] == 31
    assert len(payload["documents"]) == 24
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
    assert MULTI_SLOTS == 5
    assert not set(multi_documents()) & set(RESERVED_DOCUMENTS)
    assert all(len(cell.answers) >= 2 for cell in multi_cells())


def test_single_answer_cell_stays_one_excerpt() -> None:
    unit = _unit("auto", PATH, AUTO)
    jev = MultiScriptJev()
    status, source, excerpt, _excerpt_id = answer_cell(
        jev,
        user_question="Förlängs avtalet automatiskt?",
        examined=[unit],
        model="jev-latest",
        timeout_seconds=8.0,
    )
    assert status == ANSWERED
    assert source == "auto"
    assert excerpt in unit.text
    assert "answer_1" not in jev.question_keys[0]


def test_multi_answer_cell_returns_several_listed_excerpts() -> None:
    unit = _unit("notice", PATH, NOTICE)
    jev = MultiScriptJev()
    status, pairs = answer_cell_multi(
        jev,
        user_question="Vilken uppsägningstid gäller enligt avtalet?",
        examined=[unit],
        model="jev-latest",
        timeout_seconds=8.0,
    )
    assert status == ANSWERED
    excerpts = [excerpt for _source, excerpt, _excerpt_id in pairs]
    assert any("tre månader" in excerpt for excerpt in excerpts)
    assert any("14 dagar" in excerpt for excerpt in excerpts)
    assert all(excerpt in unit.text for excerpt in excerpts)
    assert "answer_1" in jev.question_keys[0]
    assert jev.calls == 1
    spans = proposed_spans([unit])
    assert all(span["text"] in unit.text for span in spans)


def test_score_multi_counts_hits_and_extras() -> None:
    gold = _golds()[(PATH, "notice-period")]
    hit = score_multi_cell(
        {
            "status": ANSWERED,
            "answer": "tre månader",
            "sources": [
                {"excerpt": "Uppsägningstiden är tre månader för båda parter."},
                {"excerpt": "Under provanställning är den 14 dagar."},
                {"excerpt": "Vite utgår med 50 000 kronor."},
            ],
        },
        gold,
    )
    assert hit["gold_n"] == 2
    assert hit["gold_hits"] == 2
    assert hit["predicted_n"] == 3
    assert hit["extra_n"] == 1
    assert hit["multi_gold"] is True


def test_multi_run_keeps_the_same_five_units() -> None:
    jev = MultiScriptJev()
    payload = run_tabular_multi(
        units=_units(),
        structures={},
        queries=_queries(),
        jev=jev,
        documents=(PATH,),
        question_ids=("auto-renewal", "notice-period"),
        golds=_golds(),
    )
    assert payload["same_five_units"] is True
    assert payload["one_jev_call"] is True
    assert payload["does_not_change_retrieval"] is True
    assert payload["do_not_start_product_from_this_run"] is True
    assert payload["jev_calls"] == 4
    assert jev.calls == 4
    single = [cell for cell in payload["cells"] if cell["variant"] == SINGLE]
    multi = [cell for cell in payload["cells"] if cell["variant"] == MULTI]
    assert [cell["retrieval"]["candidate_keys"] for cell in single] == [
        cell["retrieval"]["candidate_keys"] for cell in multi
    ]
    assert all(len(cell["retrieval"]["candidate_keys"]) == 5 for cell in payload["cells"])
    notice = next(row for row in payload["scored"][MULTI] if row["question_id"] == "notice-period")
    single_notice = next(
        row for row in payload["scored"][SINGLE] if row["question_id"] == "notice-period"
    )
    assert notice["gold_hits"] == 2
    assert notice["extra_n"] == 0
    assert single_notice["gold_hits"] == 0
    assert payload["headline"][MULTI]["multi_gold_hits"] == 2
    assert payload["headline"][SINGLE]["multi_gold_hits"] == 0
    assert payload["decision"]["more_gold_hits_without_more_extras"] is True


def test_multi_run_counts_false_extra_answers() -> None:
    payload = run_tabular_multi(
        units=_units(),
        structures={},
        queries=_queries(),
        jev=MultiScriptJev(extra="Ingen sekretess"),
        documents=(PATH,),
        question_ids=("notice-period",),
        golds=_golds(),
    )
    notice = payload["scored"][MULTI][0]
    assert notice["gold_hits"] == 2
    assert notice["extra_n"] >= 1
    assert payload["paired"]["more_extras"] == 1


def test_multi_run_refuses_reserved_holdout() -> None:
    with pytest.raises(ValueError, match="reserved"):
        run_tabular_multi(
            documents=(RESERVED_DOCUMENTS[0],),
            golds={},
            queries={},
            jev=HoldoutJev(),
            context=GraphContext([], {}, {}, {}),
        )


def test_multi_run_does_not_reopen_graph_during_jev(monkeypatch) -> None:
    def boom(**_kwargs):
        raise AssertionError("graph reopened during multi")

    monkeypatch.setattr("overgraph_ingest.tabular.multi_run._load_context", boom)
    payload = run_tabular_multi(
        context=GraphContext(_units(), {}, {}, {}),
        queries=_queries(),
        jev=MultiScriptJev(),
        documents=(PATH,),
        question_ids=("auto-renewal", "notice-period"),
        golds=_golds(),
    )
    assert payload["jev_calls"] == 4


def test_multi_run_baseline_is_write_once(tmp_path: Path) -> None:
    before_c8 = C8.read_bytes()
    before_reject = PRESENT_REJECT.read_bytes()
    payload = run_tabular_multi(
        units=_units(),
        structures={},
        queries=_queries(),
        jev=MultiScriptJev(),
        documents=(PATH,),
        question_ids=("auto-renewal", "notice-period"),
        golds=_golds(),
    )
    write_multi_run_table(payload, tmp_path)
    target = tmp_path / "multi-run.json"
    write_multi_run_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_multi_run_baseline(payload, target)
    with pytest.raises(FileExistsError):
        write_multi_run_baseline(payload, C8)
    if MULTI_RUN_PATH.exists():
        before_run = MULTI_RUN_PATH.read_bytes()
        with pytest.raises(FileExistsError):
            write_multi_run_baseline(payload, MULTI_RUN_PATH)
        assert MULTI_RUN_PATH.read_bytes() == before_run
    assert C8.read_bytes() == before_c8
    assert PRESENT_REJECT.read_bytes() == before_reject
    table = (tmp_path / "multi-run-v1.md").read_text(encoding="utf-8")
    assert "Gold hits" in table
    assert "Multi-span extras" in table


def test_frozen_multi_run_found_gold_and_extras() -> None:
    frozen = load_tabular_multi_run_baseline()
    assert frozen["id"] == "phase2-tabular-multi-run-v1"
    assert frozen["does_not_change_retrieval"] is True
    assert frozen["same_five_units"] is True
    assert frozen["one_jev_call"] is True
    assert frozen["does_not_run_reserved_holdout"] is True
    assert frozen["default_remains_d"] is True
    assert frozen["do_not_start_product_from_this_run"] is True
    assert frozen["jev_calls"] == 240
    assert frozen["headline"]["single"]["multi_gold_hits"] == 32
    assert frozen["headline"]["multi"]["multi_gold_hits"] == 46
    assert frozen["headline"]["single"]["multi_extra_n"] == 0
    assert frozen["headline"]["multi"]["multi_extra_n"] == 4
    assert frozen["paired"]["more_gold"] == 13
    assert frozen["paired"]["more_extras"] == 8
    assert frozen["decision"]["more_gold_hits_without_more_extras"] is False
    assert RETRIEVAL_CONCLUSIONS["tabular_multi_run"] == "measured_v1"
    assert RETRIEVAL_CONCLUSIONS["tabular_multi_found_more_gold"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_multi_added_extras"] is True
    assert RETRIEVAL_CONCLUSIONS["tabular_multi_did_not_win_without_extras"] is True
    assert RETRIEVAL_CONCLUSIONS["do_not_start_product_from_multi_run"] is True
    assert instruction_for(PROMPT_P0) == P0_STATUS_INSTRUCTIONS
    assert DEFAULT_K == 5
