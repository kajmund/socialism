from __future__ import annotations

from overgraph_ingest.jev.client import JevError, JevResult, JevUsage
from overgraph_ingest.retrieval.bm25_answer import run_bm25_answer_test
from overgraph_ingest.retrieval.evidence_gold import (
    CellEvidenceGold,
    EvidenceAlternative,
    EvidenceGroup,
)
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND

PATH = "a.docx"
FORWARD = "Avtalet förlängs automatiskt med tolv månader."
NEGATIVE = "Det förlängs inte automatiskt."
NOISE = "Helt annan text."


def _unit(key: str, text: str) -> StoredUnit:
    return StoredUnit(1, key, "doc", PATH, text, None, None, content_hash=key)


def _payload() -> dict[str, object]:
    def candidate(rank: int, key: str) -> dict[str, object]:
        return {
            "rank": rank,
            "key": key,
            "relative_path": PATH,
            "document_id": "doc",
            "score": 1.0,
            "branch": {},
            "label": "relevant" if key == "u1" else "other",
        }

    return {
        "profiles": {
            "sv_stem_v1": {
                "document": {
                    "rows": [
                        {
                            "question_id": "auto-renewal",
                            "relative_path": PATH,
                            "arms": {
                                "dense_bm25": {"candidates": [candidate(1, "u1")]},
                                "hybrid_current": {"candidates": [candidate(1, "u2")]},
                            },
                        },
                    ]
                }
            }
        },
        "manifest": {"corpus": {"units_metadata": {"units_hash_root": "snap"}}},
    }


class ForwardJev:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        if self.fail:
            raise JevError("upstream timeout")
        if "status" not in questions:
            raise AssertionError("answer test must not classify")
        excerpt = next(
            (
                key
                for key, text in questions["excerpt"]["criteria"].items()
                if key != "none" and "förlängs" in text
            ),
            None,
        )
        if excerpt is None:
            return _result(NOT_FOUND, "none", "none")
        source = next(
            key
            for key, text in questions["source"]["criteria"].items()
            if key != "none" and "förlängs" in text
        )
        return _result(ANSWERED, source, excerpt)


def _result(status: str, source: str, excerpt: str) -> JevResult:
    answers = {
        "status": {"choice": status},
        "source": {"choice": source},
        "excerpt": {"choice": excerpt},
    }
    return JevResult(
        answers=answers,
        model="jev-latest",
        latency_ms=1.0,
        usage=JevUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
        raw={"answers": answers},
    )


def _cells() -> list[CellEvidenceGold]:
    return [
        CellEvidenceGold(
            question_id="auto-renewal",
            relative_path=PATH,
            split="development",
            answerability="answerable",
            positive_property=True,
            groups=(
                EvidenceGroup(
                    "answer",
                    (EvidenceAlternative(PATH, "förlängs automatiskt"),),
                ),
            ),
        )
    ]


def test_answer_test_uses_frozen_top_five_and_p0() -> None:
    units = [_unit("u1", FORWARD), _unit("u2", NOISE)]
    jev = ForwardJev()
    payload = run_bm25_answer_test(
        _payload(),
        units=units,
        cells=_cells(),
        jev=jev,
        profile="sv_stem_v1",
    )
    assert payload["status"] == "completed"
    assert payload["same_prompt"] == "P0"
    assert payload["same_answer_cell"] is True
    assert payload["no_new_retrieval"] is True
    assert payload["summary"]["dense_bm25"]["answer_correct"] == 1.0
    assert payload["summary"]["hybrid_current"]["answer_correct"] == 0.0
    assert payload["paired"]["improved"] == 1
    assert payload["paired"]["regressed"] == 0


def test_api_error_is_blocked_not_abstention() -> None:
    units = [_unit("u1", FORWARD), _unit("u2", NOISE)]
    payload = run_bm25_answer_test(
        _payload(),
        units=units,
        cells=_cells(),
        jev=ForwardJev(fail=True),
        profile="sv_stem_v1",
    )
    assert payload["status"] == "blocked"
    assert payload["blocked_reason"] == "jev_api_error"
    assert payload["summary"]["dense_bm25"]["errors"] > 0
    assert payload["summary"]["dense_bm25"]["abstentions"] == 0


def test_negative_evidence_is_correct_answer_but_citation_separate() -> None:
    from overgraph_ingest.retrieval.bm25_answer import AnswerArm, _score_answer
    from overgraph_ingest.tabular.contract import CellResult, SourceRef

    result = CellResult(
        document_id="a",
        relative_path=PATH,
        question_id="auto-renewal",
        question="Förlängs avtalet automatiskt?",
        variant="dense_bm25",
        status=ANSWERED,
        answer=NEGATIVE,
        source_unit_ids=["u3"],
        sources=[
            SourceRef(
                document_id="doc",
                unit_id="u3",
                relative_path=PATH,
                char_start=0,
                char_end=len(NEGATIVE),
                excerpt=NEGATIVE,
                clause_number="",
                validated=True,
            )
        ],
    )
    cell = CellEvidenceGold(
        question_id="auto-renewal",
        relative_path=PATH,
        split="development",
        answerability="negative",
        positive_property=False,
        groups=(
            EvidenceGroup(
                "explicit_no",
                (EvidenceAlternative(PATH, "förlängs inte automatiskt"),),
            ),
        ),
    )
    scored = _score_answer(
        AnswerArm(
            arm="dense_bm25",
            cell=cell,
            result=result,
            relevant_keys={"u3"},
        )
    )
    assert scored["answer_correct"] is True
    assert scored["citation_correct"] is True
    assert scored["false_answer"] is False
