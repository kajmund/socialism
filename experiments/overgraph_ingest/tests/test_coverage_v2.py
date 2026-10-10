from overgraph_ingest.coverage.cache import CachedAnswer
from overgraph_ingest.coverage.controller import FAIR, TOUCHED, metrics_payload, run_controller
from overgraph_ingest.coverage.state import (
    EVIDENCE_FOUND,
    NEEDS_ANALYSIS,
    NO_EVIDENCE_YET,
    UNEXAMINED,
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
        "s4": {"parent_id": "root", "clause_number": "4", "title": "4. Informationssäkerhet och dataskydd"},
    }
    return GraphContext(
        units=units,
        structures={unit.structure_id: structures.get(unit.structure_id, structures["s"]) for unit in units} | structures,
        neighbors={unit.key: ("", "") for unit in units},
        parent_texts={"root": "", "s": "1. Villkor", "s4": "4. Informationssäkerhet och dataskydd"},
    )


def _gold(*, proof_kind: str = "EXISTS") -> RetrievalGold:
    return RetrievalGold(
        id="t",
        query="q",
        classify_question="Innehåller texten villkoret?",
        relevant_units=[GoldSpan("a.docx", "rätt")],
        hard_negatives=[],
        document_gold=("a.docx",),
        proof_kind=proof_kind,
        coverage_groups=[CoverageGroup("a.docx", ("rätt", "syskon"))] if proof_kind == "COMPOSITE" else [],
    )


def test_existence_yes_wins_over_uncertain() -> None:
    doc = DocumentState(
        "a.docx",
        4,
        retrieved=[
            UnitRecord("u1", "UNCERTAIN", "global"),
            UnitRecord("u2", "YES", "in_document"),
        ],
    )
    assert resolve_status(doc, proof_kind="EXISTS") == EVIDENCE_FOUND
    assert resolve_status(doc, proof_kind="COMPOSITE") == NEEDS_ANALYSIS


def test_retrieved_is_not_classified_or_verified_absent() -> None:
    doc = DocumentState(
        "a.docx",
        3,
        retrieved=[UnitRecord("u1", None, "global")],
    )
    assert resolve_status(doc, proof_kind="EXISTS") == "RETRIEVED"
    doc.retrieved[0].predicted = "NO"
    assert resolve_status(doc, proof_kind="EXISTS") == NO_EVIDENCE_YET
    assert resolve_status(doc, proof_kind="EXISTS") != VERIFIED_ABSENT


def test_existence_stops_after_first_yes() -> None:
    a1 = _unit("a1", "a.docx", "rätt", 1)
    a2 = _unit("a2", "a.docx", "annat", 2)
    b1 = _unit("b1", "b.docx", "oviktigt", 1)
    b2 = _unit("b2", "b.docx", "mer", 2)
    units = [a1, a2, b1, b2]
    ranked = [_hit(b1, 1), _hit(a2, 2), _hit(a1, 3)]
    fake = FakeJev({"b1": "NO", "a2": "NO", "a1": "YES"})
    result = run_controller(
        variant=FAIR,
        ranked=ranked,
        context=_context(units),
        gold=_gold(),
        client=fake,
        cache={},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=2,
        max_passes=3,
    )
    assert result.documents["a.docx"].status == EVIDENCE_FOUND
    assert result.documents["b.docx"].status == NO_EVIDENCE_YET
    assert "a1" in {row.key for row in result.documents["a.docx"].retrieved}
    assert fake.asked.count("a1") == 1


def test_cache_prevents_second_jev_call() -> None:
    a1 = _unit("a1", "a.docx", "rätt", 1)
    b1 = _unit("b1", "b.docx", "oviktigt", 1)
    fake = FakeJev({"b1": "NO"})
    result = run_controller(
        variant=TOUCHED,
        ranked=[_hit(a1, 1), _hit(b1, 2)],
        context=_context([a1, b1]),
        gold=_gold(),
        client=fake,
        cache={"a1": CachedAnswer("YES", 0.9, "c8")},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=2,
        max_passes=1,
    )
    assert "a1" not in fake.asked
    assert result.cache_hits == 1
    assert result.documents["a.docx"].status == EVIDENCE_FOUND


def test_touched_does_not_open_unexamined_documents() -> None:
    a1 = _unit("a1", "a.docx", "rätt", 1)
    b1 = _unit("b1", "b.docx", "andra rätt", 1)
    c1 = _unit("c1", "c.docx", "oviktigt", 1)
    c2 = _unit("c2", "c.docx", "mer", 2)
    gold = RetrievalGold(
        id="t",
        query="q",
        relevant_units=[GoldSpan("a.docx", "rätt"), GoldSpan("b.docx", "andra rätt")],
        hard_negatives=[],
        document_gold=("a.docx", "b.docx"),
    )
    fake = FakeJev({"c1": "NO", "b1": "YES"})
    result = run_controller(
        variant=TOUCHED,
        ranked=[_hit(c1, 1), _hit(a1, 2), _hit(b1, 3)],
        context=_context([a1, b1, c1, c2]),
        gold=gold,
        client=fake,
        cache={},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=1,
        max_passes=2,
    )
    assert result.documents["a.docx"].status == UNEXAMINED
    assert result.documents["c.docx"].status == NO_EVIDENCE_YET
    metrics = metrics_payload(result, gold)
    assert "a.docx" in metrics["unresolved_relevant_documents"]
    assert metrics["false_negative_documents"] == []


def test_fair_opens_unexamined_and_punkt_hop_is_used() -> None:
    start = _unit(
        "u6",
        "d.docx",
        "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot punkt 4.",
        2,
        "s",
    )
    clause = _unit("u4", "d.docx", "4. Informationssäkerhet och dataskydd", 1, "s4")
    extra = _unit("u5", "d.docx", "annan text", 3, "s")
    fake = FakeJev({"u6": "UNCERTAIN", "u4": "NO"})
    gold = RetrievalGold(
        id="t",
        query="q",
        relevant_units=[],
        hard_negatives=[],
        document_gold=(),
        proof_kind="COMPOSITE",
    )
    result = run_controller(
        variant=FAIR,
        ranked=[_hit(start, 1), _hit(clause, 2)],
        context=_context([start, clause, extra]),
        gold=gold,
        client=fake,
        cache={},
        question="q",
        model="jev",
        timeout_seconds=1,
        concurrency=1,
        global_k=1,
        max_passes=2,
    )
    assert "u4" in fake.asked
    assert result.hop_fetches >= 1
    assert result.documents["d.docx"].status != VERIFIED_ABSENT
    assert result.documents["d.docx"].status in {NEEDS_ANALYSIS, NO_EVIDENCE_YET}
