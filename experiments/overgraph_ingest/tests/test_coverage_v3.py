from overgraph_ingest.coverage.budget import budget_metrics, run_budget_controller
from overgraph_ingest.coverage.cache import CachedAnswer
from overgraph_ingest.coverage.state import (
    BUDGET_EXHAUSTED,
    EVIDENCE_FOUND,
    NO_EVIDENCE_YET,
    VERIFIED_ABSENT,
    DocumentState,
    UnitRecord,
    resolve_status,
)
from overgraph_ingest.jev.candidates import GraphContext
from overgraph_ingest.jev.client import JevResult, JevUsage
from overgraph_ingest.retrieval.gold import CoverageGroup, GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit


class FakeJev:
    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = labels
        self.asked: list[str] = []

    def ask(self, *, state, questions, model, timeout_seconds):
        self.asked.extend(questions)
        return JevResult(
            answers={
                key: {"choice": self.labels[key], "confidence": 0.9} for key in questions
            },
            model=model,
            latency_ms=5.0,
            usage=JevUsage(),
            raw={},
        )


def _unit(key: str, path: str, text: str, sequence: int, structure_id: str = "s") -> StoredUnit:
    return StoredUnit(sequence, key, f"d-{path}", path, text, None, None, structure_id, sequence)


def _hit(unit: StoredUnit, rank: int) -> SearchHit:
    return SearchHit(unit.node_id, unit.key, 1.0 / rank, rank, unit.document_id, unit.relative_path, unit.text)


def _context(units: list[StoredUnit]) -> GraphContext:
    structures = {
        "s": {"parent_id": "root", "clause_number": "1", "title": "1. Villkor"},
        "s4": {"parent_id": "root", "clause_number": "4", "title": "4. Avtalstid och uppsägning"},
        "s41": {"parent_id": "s4", "clause_number": "4.1", "title": "4.1 Förlängning"},
        "scap": {"parent_id": "s12", "clause_number": "12.3", "title": "12.3 Cap"},
        "scarve": {"parent_id": "s12", "clause_number": "12.4", "title": "12.4 Carve-out"},
    }
    return GraphContext(
        units=units,
        structures={
            unit.structure_id: structures.get(unit.structure_id, structures["s"]) for unit in units
        }
        | structures,
        neighbors={unit.key: ("", "") for unit in units},
        parent_texts={"root": "", "s": "1. Villkor", "s4": "4. Avtalstid och uppsägning"},
    )


def _gold(*, proof_kind: str = "EXISTS", path: str = "a.docx", extra_docs: tuple[str, ...] = ()) -> RetrievalGold:
    return RetrievalGold(
        id="t",
        query="q",
        classify_question="Innehåller texten villkoret?",
        relevant_units=[GoldSpan(path, "rätt")],
        hard_negatives=[],
        document_gold=(path, *extra_docs),
        proof_kind=proof_kind,
    )


def test_exists_yes_stops_inside_budget() -> None:
    yes = _unit("a1", "a.docx", "rätt", 1)
    later = _unit("a2", "a.docx", "annat", 2)
    other = _unit("b1", "b.docx", "oviktigt", 1)
    extra = _unit("b2", "b.docx", "mer", 2)
    fake = FakeJev({"a1": "YES", "b1": "NO"})
    result = run_budget_controller(
        ranked=[_hit(yes, 1), _hit(other, 2), _hit(later, 3)],
        context=_context([yes, later, other, extra]),
        gold=_gold(),
        client=fake,
        cache={},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=2,
        budget=3,
    )
    assert result.documents["a.docx"].status == EVIDENCE_FOUND
    assert "a2" not in {row.key for row in result.documents["a.docx"].retrieved}
    assert "a2" not in fake.asked


def test_budget_one_does_not_classify_second_unit() -> None:
    first = _unit("a1", "a.docx", "första", 1)
    second = _unit("a2", "a.docx", "rätt", 2)
    fake = FakeJev({"a1": "NO", "a2": "YES"})
    result = run_budget_controller(
        ranked=[_hit(first, 1), _hit(second, 2)],
        context=_context([first, second]),
        gold=_gold(),
        client=fake,
        cache={},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=2,
        budget=1,
    )
    assert [row.key for row in result.documents["a.docx"].retrieved] == ["a1"]
    assert "a2" not in fake.asked
    assert result.documents["a.docx"].status == BUDGET_EXHAUSTED
    assert result.documents["a.docx"].status != VERIFIED_ABSENT


def test_absence_only_verified_when_every_unit_classified() -> None:
    doc = DocumentState(
        "a.docx",
        2,
        retrieved=[UnitRecord("u1", "NO", "global", text="nej")],
    )
    assert resolve_status(doc, proof_kind="EXISTS", budget=1) == BUDGET_EXHAUSTED
    assert resolve_status(doc, proof_kind="ABSENCE", budget=1) == BUDGET_EXHAUSTED
    doc.retrieved.append(UnitRecord("u2", "NO", "in_document", text="heller inte"))
    assert resolve_status(doc, proof_kind="EXISTS") == NO_EVIDENCE_YET
    assert resolve_status(doc, proof_kind="ABSENCE") == VERIFIED_ABSENT


def test_uncertain_heading_classifies_child() -> None:
    heading = _unit("h", "d.docx", "4. Avtalstid och uppsägning\n", 1, "s4")
    child = _unit("c", "d.docx", "4.1 Avtalet förlängs därefter med en månad i taget.", 2, "s41")
    extra = _unit("e", "d.docx", "annan text", 3, "s")
    fake = FakeJev({"h": "UNCERTAIN", "c": "YES"})
    result = run_budget_controller(
        ranked=[_hit(heading, 1)],
        context=_context([heading, child, extra]),
        gold=_gold(path="d.docx"),
        client=fake,
        cache={},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=1,
        budget=2,
    )
    assert "c" in fake.asked
    assert result.hop_fetches >= 1
    assert result.documents["d.docx"].status == EVIDENCE_FOUND


def test_composite_needs_both_parts() -> None:
    carve = _unit(
        "carve",
        "a.docx",
        "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretess.",
        2,
        "scarve",
    )
    cap = _unit(
        "cap",
        "a.docx",
        "DevBrains sammanlagda ansvar per avtalsår är begränsat till de avgifter som Kunden har betalat under de senaste tolv (12) månaderna.",
        1,
        "scap",
    )
    extra = _unit("x", "a.docx", "övrigt", 3, "s")
    gold = RetrievalGold(
        id="liability-secrecy-carveout",
        query="q",
        relevant_units=[GoldSpan("a.docx", "sekretess")],
        hard_negatives=[],
        document_gold=("a.docx",),
        proof_kind="COMPOSITE",
        coverage_groups=[
            CoverageGroup(
                "a.docx",
                (
                    "DevBrains sammanlagda ansvar per avtalsår är begränsat till de avgifter som Kunden har betalat under de senaste tolv (12) månaderna.",
                    "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretess.",
                ),
            )
        ],
    )
    fake = FakeJev({"carve": "YES", "cap": "NO"})
    result = run_budget_controller(
        ranked=[_hit(carve, 1), _hit(cap, 2)],
        context=_context([carve, cap, extra]),
        gold=gold,
        client=fake,
        cache={},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=1,
        budget=3,
    )
    assert "cap" in fake.asked
    assert result.documents["a.docx"].parts_complete()
    assert result.documents["a.docx"].status == EVIDENCE_FOUND
    metrics = budget_metrics(result, gold, budget=3)
    assert metrics["composite_groups"][0]["complete"] is True
    assert metrics["false_negative_documents"] == []


def test_budget_exhausted_relevant_is_not_negative() -> None:
    first = _unit("a1", "a.docx", "första", 1)
    second = _unit("a2", "a.docx", "rätt", 2)
    gold = _gold()
    fake = FakeJev({"a1": "NO"})
    result = run_budget_controller(
        ranked=[_hit(first, 1), _hit(second, 2)],
        context=_context([first, second]),
        gold=gold,
        client=fake,
        cache={},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=1,
        budget=1,
    )
    metrics = budget_metrics(result, gold, budget=1)
    assert "a.docx" in metrics["unresolved_relevant_documents"]
    assert metrics["false_negative_documents"] == []
    assert metrics["budget_exhausted_relevant"] == ["a.docx"]


def test_cache_counts_toward_budget_but_is_not_reasked() -> None:
    unit = _unit("a1", "a.docx", "rätt", 1)
    extra = _unit("a2", "a.docx", "mer", 2)
    fake = FakeJev({})
    result = run_budget_controller(
        ranked=[_hit(unit, 1)],
        context=_context([unit, extra]),
        gold=_gold(),
        client=fake,
        cache={"a1": CachedAnswer("YES", 0.9, "c8")},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=1,
        budget=1,
    )
    assert fake.asked == []
    assert result.cache_hits == 1
    assert result.documents["a.docx"].status == EVIDENCE_FOUND
