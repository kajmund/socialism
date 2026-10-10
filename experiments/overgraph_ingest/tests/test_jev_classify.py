import threading
import time

import pytest

from overgraph_ingest.jev.classify import (
    CLASSIFY_CANDIDATES_PER_CALL,
    DEFAULT_CLASSIFY_CONCURRENCY,
    Judgment,
    classify_candidates,
    expected_label,
)
from overgraph_ingest.jev.candidates import ClassifiedCandidate
from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.jev.baseline import (
    ARCHITECTURE,
    BASELINE_ID,
    load_official_classify_baseline,
)
from overgraph_ingest.jev.evaluate import (
    analyze_coverage_groups,
    compare_judgments,
    evaluate_judgments,
    threshold_stability,
)
from overgraph_ingest.retrieval.gold import CoverageGroup, RetrievalGold
from overgraph_ingest.jev.run import EXPERIMENT_CELLS
from overgraph_ingest.jev.questions import CHOICE_QUESTION, choice_question, parse_choice
from overgraph_ingest.retrieval.gold import load_retrieval_gold
from tests.test_retrieval import OFFICIAL_GOLD


class FakeJev:
    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = labels
        self.calls = 0
        self.last_state = None

    def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        self.last_state = state
        return JevResult(
            answers={
                key: {"choice": self.labels[key], "confidence": 0.9} for key in questions
            },
            model=model,
            latency_ms=12.0,
            usage=JevUsage(),
            raw={},
        )


def _candidate(key: str, gold_label: str, text: str) -> ClassifiedCandidate:
    return ClassifiedCandidate(
        key=key,
        rank=1,
        score=1.0,
        relative_path=f"{key}.docx",
        document_id=key,
        text=text,
        structure_title="4. Avtalstid",
        parent_title="Avtal",
        parent_text="4. Avtalstid och uppsägning",
        previous_text="föregående villkor",
        next_text="nästa villkor",
        gold_label=gold_label,
    )


def test_classify_rejects_prompt_batching() -> None:
    fake = FakeJev({"pos": "YES"})
    with pytest.raises(ValueError, match="one candidate per prompt"):
        classify_candidates(
            fake,
            [_candidate("pos", "relevant", "förlängs automatiskt")],
            model="jev-test",
            timeout_seconds=1,
            batch_size=4,
            context="none",
        )


def test_official_classify_baseline_is_c8() -> None:
    payload = load_official_classify_baseline()
    assert payload["id"] == BASELINE_ID
    assert payload["architecture"] == ARCHITECTURE
    assert payload["architecture"]["classify_candidates_per_call"] == CLASSIFY_CANDIDATES_PER_CALL
    assert payload["architecture"]["concurrency_cap"] == DEFAULT_CLASSIFY_CONCURRENCY
    assert payload["architecture"]["prompt_batching"] == "rejected_for_classify"
    headline = payload["headline"]
    assert headline["precision"] == 0.95
    assert headline["recall"] == 0.95
    assert headline["concurrency"] == 8
    assert headline["batch_size"] == 1
    assert headline["model_calls"] == 50
    assert headline["errors"] == 0
    assert headline["false_positives"] == ["Avtal_02_Provanstallningsavtal.docx"]
    assert headline["false_negatives"] == ["Avtal_18_Hyresavtal_bostad.docx"]
    assert payload["threshold_stability"]["thresholds"]["0.7"]["unstable"] == 5
    assert payload["concurrency_sweep"][2]["variant"] == "C@8"


def test_official_gold_keeps_twenty_positives_and_watches_avtal_23() -> None:
    gold = load_retrieval_gold(OFFICIAL_GOLD)
    assert len(gold.relevant_documents) == 20
    assert gold.watch_negatives[0].relative_path.startswith("Avtal_23_")


def test_parse_choice_and_expected_labels() -> None:
    assert parse_choice({"u1": {"choice": "yes", "confidence": 0.8}}, "u1") == ("YES", 0.8)
    assert expected_label("relevant") == "YES"
    assert expected_label("hard_negative") == "NO"
    assert expected_label("watch_negative") == "NO"


def test_experiment_a_classifies_one_candidate_per_call() -> None:
    candidates = [
        _candidate("pos", "relevant", "Avtalet förlängs automatiskt."),
        _candidate("neg", "hard_negative", "Det förlängs inte automatiskt."),
    ]
    fake = FakeJev({"pos": "YES", "neg": "NO"})
    judgments, _elapsed = classify_candidates(
        fake,
        candidates,
        model="jev-test",
        timeout_seconds=1,
        batch_size=1,
        context="none",
    )
    assert fake.calls == 2
    assert "previous_text" not in fake.last_state["candidates"][0]
    assert "parent_text" not in fake.last_state["candidates"][0]
    metrics = evaluate_judgments(judgments)
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["false_positives"] == []
    assert metrics["false_negatives"] == []


def test_uncertain_is_not_a_silent_drop() -> None:
    judgments = [
        Judgment(
            key="pos",
            rank=1,
            relative_path="a.docx",
            gold_label="relevant",
            expected="YES",
            predicted="UNCERTAIN",
            confidence=0.4,
            latency_ms=1,
            call_index=0,
            batch_size=1,
            error=None,
            text="oklart",
        )
    ]
    metrics = evaluate_judgments(judgments)
    assert metrics["recall"] == 0.0
    assert metrics["false_negatives"] == []
    assert len(metrics["uncertain_relevant"]) == 1


def test_watch_negative_yes_is_reported() -> None:
    judgments = [
        Judgment(
            key="watch",
            rank=2,
            relative_path="Avtal_23.docx",
            gold_label="watch_negative",
            expected="NO",
            predicted="YES",
            confidence=0.7,
            latency_ms=1,
            call_index=0,
            batch_size=1,
            error=None,
            text="Hyrestiden förlängs",
        )
    ]
    metrics = evaluate_judgments(judgments)
    assert metrics["watch_predicted_yes"][0]["relative_path"] == "Avtal_23.docx"


def test_experiment_b1_sends_parent_clause_not_neighbors() -> None:
    fake = FakeJev({"pos": "YES"})
    classify_candidates(
        fake,
        [_candidate("pos", "relevant", "förlängs därefter")],
        model="jev-test",
        timeout_seconds=1,
        batch_size=1,
        context="parent",
    )
    row = fake.last_state["candidates"][0]
    assert row["text"] == "förlängs därefter"
    assert row["parent_title"] == "Avtal"
    assert row["parent_text"] == "4. Avtalstid och uppsägning"
    assert "previous_text" not in row
    assert fake.last_state["judge"] == "candidate_text_only"
    assert "Classify only the candidate" in CHOICE_QUESTION["instructions"]
    fake_notice = FakeJev({"pos": "YES"})
    classify_candidates(
        fake_notice,
        [_candidate("pos", "relevant", "tre månaders uppsägningstid")],
        model="jev-test",
        timeout_seconds=1,
        batch_size=1,
        context="none",
        question="Innehåller texten en stående uppsägningstid för att avsluta avtalet?",
    )
    assert "uppsägningstid" in fake_notice.last_state["task"]
    assert "uppsägningstid" in choice_question("x uppsägningstid")["instructions"]


def test_experiment_b2_sends_neighbors_not_parent() -> None:
    fake = FakeJev({"pos": "YES"})
    classify_candidates(
        fake,
        [_candidate("pos", "relevant", "förlängs därefter")],
        model="jev-test",
        timeout_seconds=1,
        batch_size=1,
        context="adjacent",
    )
    row = fake.last_state["candidates"][0]
    assert row["previous_text"] == "föregående villkor"
    assert row["next_text"] == "nästa villkor"
    assert "parent_text" not in row


def test_batch_size_still_sends_several_candidates_in_one_call() -> None:
    candidates = [
        _candidate("a", "relevant", "förlängs automatiskt"),
        _candidate("b", "other", "sekretess"),
        _candidate("c", "other", "tills vidare"),
        _candidate("d", "hard_negative", "förlängs inte automatiskt"),
    ]
    fake = FakeJev({"a": "YES", "b": "NO", "c": "NO", "d": "NO"})
    judgments, _elapsed = classify_candidates(
        fake,
        candidates,
        model="jev-test",
        timeout_seconds=1,
        batch_size=4,
        context="none",
        allow_prompt_batch=True,
    )
    assert fake.calls == 1
    assert {item.predicted for item in judgments} == {"YES", "NO"}
    assert evaluate_judgments(judgments)["model_calls"] == 1


class CountingJev:
    def __init__(self, labels: dict[str, str], delay: float = 0.05) -> None:
        self.labels = labels
        self.delay = delay
        self.lock = threading.Lock()
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    def ask(self, *, state, questions, model, timeout_seconds):
        with self.lock:
            self.calls += 1
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        time.sleep(self.delay)
        with self.lock:
            self.in_flight -= 1
        return JevResult(
            answers={key: {"choice": self.labels[key], "confidence": 0.9} for key in questions},
            model=model,
            latency_ms=self.delay * 1000,
            usage=JevUsage(),
            raw={},
        )


def test_experiment_c_runs_independent_calls_concurrently() -> None:
    candidates = [_candidate(f"u{index}", "other", "sekretess") for index in range(8)]
    fake = CountingJev({item.key: "NO" for item in candidates})
    started = time.perf_counter()
    judgments, elapsed = classify_candidates(
        fake,
        candidates,
        model="jev-test",
        timeout_seconds=1,
        batch_size=1,
        context="none",
        concurrency=4,
    )
    assert fake.calls == 8
    assert fake.max_in_flight >= 3
    assert elapsed < 0.30
    assert time.perf_counter() - started < 0.40
    assert [item.key for item in judgments] == [item.key for item in candidates]
    assert evaluate_judgments(judgments)["model_calls"] == 8


def _judgment(key: str, *, predicted: str, expected: str, gold_label: str, path: str) -> Judgment:
    return Judgment(
        key=key,
        rank=1,
        relative_path=path,
        gold_label=gold_label,
        expected=expected,
        predicted=predicted,
        confidence=0.5,
        latency_ms=1,
        call_index=0,
        batch_size=1,
        error=None,
        text="x",
    )


def test_compare_counts_improvements_and_regressions() -> None:
    baseline = [
        {
            "key": "avtal18",
            "predicted": "NO",
            "expected": "YES",
            "confidence": 0.46,
        },
        {
            "key": "keep",
            "predicted": "YES",
            "expected": "YES",
            "confidence": 1.0,
        },
        {
            "key": "avtal02",
            "predicted": "YES",
            "expected": "NO",
            "confidence": 0.38,
        },
    ]
    current = [
        _judgment(
            "avtal18",
            predicted="YES",
            expected="YES",
            gold_label="relevant",
            path="Avtal_18_Hyresavtal_bostad.docx",
        ),
        _judgment(
            "keep",
            predicted="YES",
            expected="YES",
            gold_label="relevant",
            path="Avtal_20_Arrendeavtal.docx",
        ),
        _judgment(
            "avtal02",
            predicted="YES",
            expected="NO",
            gold_label="other",
            path="Avtal_02_Provanstallningsavtal.docx",
        ),
    ]
    delta = compare_judgments(baseline, current)
    assert delta["retained_true_yes"] == 1
    assert len(delta["changed"]) == 1
    assert delta["improvements"][0]["relative_path"].startswith("Avtal_18_")
    assert delta["regressions"] == []
    watched = {row["relative_path"]: row for row in delta["watched"]}
    assert watched["Avtal_18_Hyresavtal_bostad.docx"]["to"] == "YES"
    assert watched["Avtal_02_Provanstallningsavtal.docx"]["from"] == "YES"


def test_threshold_stability_counts_oscillating_scores() -> None:
    first = [
        {"key": "stable", "confidence": 0.96},
        {"key": "flip", "confidence": 0.65},
    ]
    second = [
        {"key": "stable", "confidence": 0.97},
        {"key": "flip", "confidence": 0.82},
    ]
    payload = threshold_stability([first, second], thresholds=(0.7,))
    assert payload["thresholds"]["0.7"]["above_in_all_runs"] == 1
    assert payload["thresholds"]["0.7"]["unstable"] == 1


def test_experiment_e_keeps_concurrency_cap_and_varies_batch_size() -> None:
    cells = EXPERIMENT_CELLS["E"]
    assert [cell.batch_size for cell in cells] == [1, 4, 8, 16]
    assert {cell.concurrency for cell in cells} == {8}
    assert {cell.context for cell in cells} == {"none"}
    assert all(cell.batch_size == 1 for cell in EXPERIMENT_CELLS["C"])


def test_coverage_group_marks_missing_sibling_without_relabeling() -> None:
    gold = RetrievalGold(
        id="carve",
        query="q",
        relevant_units=[],
        hard_negatives=[],
        coverage_groups=[
            CoverageGroup(
                "Avtal_46.docx",
                ("taket", "undantaget"),
            )
        ],
    )
    found = _candidate("cap", "relevant", "taket gäller")
    found = ClassifiedCandidate(
        **{**found.__dict__, "relative_path": "Avtal_46.docx", "next_text": "undantaget"}
    )
    judgments = [
        _judgment(
            "cap",
            predicted="UNCERTAIN",
            expected="YES",
            gold_label="relevant",
            path="Avtal_46.docx",
        )
    ]
    payload = analyze_coverage_groups(gold, [found], judgments)
    group = payload["groups"][0]
    assert group["found"] == 1
    assert group["both_in_top_k"] is False
    assert "neighbor hop" in group["graph_note"]
