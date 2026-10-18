from overgraph_ingest.coverage.chain_contract import SUPPORTED, UNDECIDED, assess_chain
from overgraph_ingest.coverage.clause_resolve import (
    AMBIGUOUS,
    CITED_CLAUSE_NOT_RELATION,
    ClauseUnit,
    RESOLVED_AND_RELATED,
    UNIQUE,
    assess_with_clauses,
    lookup_clause,
    parse_citations,
)
from overgraph_ingest.coverage.clause_run import freeze_clause_resolve_baseline, run_clause_resolve
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_clause_resolve_baseline,
)
from tests.test_decision_contract import (
    AMENDMENT_119,
    HOP_103,
    HOP_119,
    YES_103,
    YES_106,
    YES_119,
    YES_138,
    YES_173,
    _trace,
)


def _unit(path: str, number: str, title: str, text: str, key: str | None = None) -> ClauseUnit:
    return ClauseUnit(
        relative_path=path,
        key=key or f"{path}:{number}",
        clause_number=number,
        title=title,
        text=text,
    )


CATALOG_103 = [
    _unit("avtal_103.docx", "4", "4. Konfidentialitet", "4. Konfidentialitet"),
    _unit(
        "avtal_103.docx",
        "4.1",
        "4.1 Förtrolig Information",
        "4.1\tFörtrolig Information är varje uppgift om den andra partens verksamhet.\n",
    ),
    _unit(
        "avtal_103.docx",
        "5.2",
        "5.2 Tak",
        "5.2\tSkadestånd ska under avtalets hela löptid sammanlagt inte överstiga 2 500 000 kronor.\n",
    ),
]
CATALOG_138 = [
    _unit("avtal_138.docx", "12", "12. Anställning av personal", "12. Anställning av personal"),
    _unit(
        "avtal_138.docx",
        "12.1",
        "12.1 Rekreat",
        "12.1\tIngen av parterna får aktivt rekrytera personal.\n",
    ),
    _unit(
        "avtal_138.docx",
        "5.1",
        "5.1 Sekretessbelagd Information",
        "5.1\tSekretessbelagd Information är varje uppgift om den andra partens verksamhet.\n",
    ),
]
CATALOG_173 = [
    _unit("avtal_173.docx", "8", "8. Upphovsrätt och andra rättigheter", "8. Upphovsrätt"),
    _unit(
        "avtal_173.docx",
        "5.1",
        "5.1 Sekretessbelagd Information",
        "5.1\tSom Sekretessbelagd Information räknas uppgifter som part har betecknat som konfidentiella.\n",
    ),
]


def test_103_resolves_section_four_and_stays_partial() -> None:
    trace = _trace("avtal_103.docx", [("classify", "YES", YES_103), ("navigation", "NO", HOP_103)])
    assert assess_chain(trace)["examined_support"] == UNDECIDED
    judged = assess_with_clauses(trace, CATALOG_103)
    assert judged["examined_support"] == SUPPORTED
    assert judged["why"] == RESOLVED_AND_RELATED
    assert judged["investigation"] == INVESTIGATION_PARTIAL
    assert judged["finding_clause_is_not_admission"] is True
    assert judged["extra_units_fetched"] == 2


def test_wrong_previous_hop_is_not_the_referent() -> None:
    citations = parse_citations(YES_103)
    assert citations[0].number == "4"
    looked = lookup_clause(citations[0], CATALOG_103, relative_path="avtal_103.docx")
    assert looked.status == UNIQUE
    assert [unit.clause_number for unit in looked.units] == ["4", "4.1"]


def test_138_and_173_do_not_pick_another_secrecy_clause() -> None:
    for path, text, catalog in (
        ("avtal_138.docx", YES_138, CATALOG_138),
        ("avtal_173.docx", YES_173, CATALOG_173),
    ):
        judged = assess_with_clauses(_trace(path, [("classify", "YES", text)]), catalog)
        assert judged["examined_support"] == UNDECIDED
        assert judged["why"] == CITED_CLAUSE_NOT_RELATION
        assert judged["undecided_remains_searchable"] is True
        assert judged["searchable_passages"][0]["prevailing_terms_decided"] is False
        assert judged["lookups"][0]["status"] == UNIQUE


def test_duplicate_clause_numbers_are_ambiguous() -> None:
    catalog = [
        _unit("avtal_180.docx", "1", "1. Avtalsföremål", "1. Avtalsföremål"),
        _unit("avtal_180.docx", "1", "1. Tystnadsplikt", "1. Tystnadsplikt\nKonsulten är skyldig att iaktta tystnad.\n"),
    ]
    text = "Begränsningen gäller inte för ansvar vid brott mot punkt 1.\n"
    judged = assess_with_clauses(_trace("avtal_180.docx", [("classify", "YES", text)]), catalog)
    assert judged["examined_support"] == UNDECIDED
    assert judged["lookups"][0]["status"] == AMBIGUOUS


def test_finding_the_clause_is_not_admission() -> None:
    catalog = [_unit("avtal_103.docx", "4", "4. Utförande", "4. Utförande\nArbete ska utföras fackmässigt.\n")]
    judged = assess_with_clauses(
        _trace("avtal_103.docx", [("classify", "YES", YES_103)]), catalog
    )
    assert judged["examined_support"] == UNDECIDED
    assert judged["why"] == CITED_CLAUSE_NOT_RELATION


def test_existing_link_and_amendment_are_unchanged() -> None:
    assert (
        assess_with_clauses(_trace("avtal_106.docx", [("classify", "YES", YES_106)]), [])["why"]
        == "existing_link_in_unit"
    )
    judged = assess_with_clauses(
        _trace(
            "avtal_119.docx",
            [("classify", "NO", AMENDMENT_119), ("classify", "YES", YES_119), ("navigation", "NO", HOP_119)],
        ),
        [],
    )
    assert judged["examined_support"] == UNDECIDED
    assert judged["why"] == "unhandled_examined_amendment"


def test_clause_resolve_baseline() -> None:
    frozen = load_clause_resolve_baseline()
    assert frozen["known_cases_are_regression_tests"] is True
    assert frozen["headline"]["treatment_counts"]["false_approvals"] == 0
    assert frozen["headline"]["treatment_counts"]["repaired_uncertain"] == 0
    assert frozen["headline"]["delta"]["true_support"] == 3
    assert frozen["headline"]["cases"]["avtal_103.docx"]["why"] == RESOLVED_AND_RELATED
    assert frozen["headline"]["cases"]["avtal_138.docx"]["why"] == CITED_CLAUSE_NOT_RELATION
    assert RETRIEVAL_CONCLUSIONS["finding_clause_is_not_admission"] is True
    assert RETRIEVAL_CONCLUSIONS["undecided_remains_searchable"] is True
    assert RETRIEVAL_CONCLUSIONS["known_cases_are_regression_tests"] is True
    payload = run_clause_resolve()
    if payload["decisions"]:
        assert payload["treatment"]["counts"]["false_approvals"] == 0
        assert payload["delta"]["new_true_support"] == [
            "avtal_103.docx",
            "avtal_167.docx",
            "avtal_199.docx",
        ]
        assert payload["treatment"]["investigation_complete_from_proof"] is False
        assert freeze_clause_resolve_baseline(payload)["applied_to_v3"] is False
