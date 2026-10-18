from overgraph_ingest.coverage.chain_contract import SUPPORTED, UNDECIDED
from overgraph_ingest.coverage.citation_label import (
    assess_with_citation_labels,
    kind_accepts,
    lookup_labeled_clause,
)
from overgraph_ingest.coverage.citation_parse import (
    is_label_form,
    parse_object_labels,
)
from overgraph_ingest.coverage.citation_run import (
    freeze_citation_label_baseline,
    run_citation_labels,
)
from overgraph_ingest.coverage.clause_resolve import (
    ABSENT,
    AMBIGUOUS,
    CITED_CLAUSE_NOT_RELATION,
    ClauseUnit,
    RESOLVED_AND_RELATED,
    UNIQUE,
    parse_citations,
)
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_citation_label_baseline,
)
from tests.test_anaphor_resolve import _seq_trace
from tests.test_clause_resolve import CATALOG_103, CATALOG_138
from tests.test_decision_contract import HOP_107, YES_103, YES_107, YES_138, _trace


def _unit(path: str, number: str, title: str, text: str) -> ClauseUnit:
    return ClauseUnit(
        relative_path=path,
        key=f"{path}:{number or title}",
        clause_number=number,
        title=title,
        text=text,
    )


def test_parser_independent_formats_and_negatives() -> None:
    artikel = parse_object_labels(
        "Inget i denna punkt ska begränsa parts ansvar för brott mot artikel 12.\n"
    )
    assert [(row.kind, row.number) for row in artikel] == [("artikel", "12")]
    assert is_label_form(artikel[0]) is True
    klausul = parse_object_labels(
        "Begränsningen gäller inte för ansvar vid överträdelse av klausul 2.3.\n"
    )
    assert [(row.kind, row.number) for row in klausul] == [("klausul", "2.3")]
    roman = parse_object_labels(
        "Begränsningen gäller inte för ansvar vid brott mot avsnitt III.1.\n"
    )
    assert [(row.kind, row.number) for row in roman] == [("avsnitt", "III.1")]
    assert is_label_form(roman[0]) is True
    assert parse_object_labels("Se artikeln om sekretess och klausulerna i avtalet.\n") == ()
    assert parse_object_labels("Begränsningen i klausul 8.1 gäller inte vid uppsåt.\n") == ()
    old = parse_citations(YES_103)
    assert old[0].kind == "avsnitt" and old[0].number == "4"
    assert is_label_form(old[0]) is False


def test_artikel_is_not_section_and_roman_is_not_arabic() -> None:
    catalog = [
        _unit("mix.docx", "", "Artikel 8 – Tystnadsplikt", "Artikel 8 – Tystnadsplikt\nSekretess.\n"),
        _unit("mix.docx", "8.1", "8.1 Hemlig", "8.1\tSekretessbelagd Information ska hållas hemlig.\n"),
        _unit("mix.docx", "", "§ 8 Ersättning", "§ 8 Ersättning\nPriset är fast.\n"),
        _unit("mix.docx", "8", "8. Utförande", "8. Utförande\nArbete ska utföras fackmässigt.\n"),
        _unit("mix.docx", "VIII", "VIII. Tystnadsplikt", "VIII. Tystnadsplikt\nTystnadsplikt.\n"),
    ]
    artikel = parse_object_labels("brott mot artikel 8")[0]
    section = parse_object_labels("brott mot § 8")[0]
    roman = parse_object_labels("brott mot avsnitt VIII")[0]
    arabic = parse_citations("brott mot punkt 8")[0]
    looked_a = lookup_labeled_clause(artikel, catalog, relative_path="mix.docx")
    looked_s = lookup_labeled_clause(section, catalog, relative_path="mix.docx")
    looked_r = lookup_labeled_clause(roman, catalog, relative_path="mix.docx")
    looked_n = lookup_labeled_clause(arabic, catalog, relative_path="mix.docx")
    assert looked_a.status == UNIQUE
    assert all("§" not in unit.title for unit in looked_a.units)
    assert looked_s.status == UNIQUE
    assert all(unit.title.startswith("§") for unit in looked_s.units)
    assert [unit.clause_number for unit in looked_r.units] == ["VIII"]
    assert "8" in {unit.clause_number for unit in looked_n.units}
    assert "VIII" not in {unit.clause_number for unit in looked_n.units}
    assert kind_accepts(artikel, catalog[2]) is False
    assert kind_accepts(section, catalog[0]) is False


def test_independent_artikel_and_roman_can_support() -> None:
    catalog = [
        _unit("ny.docx", "", "Artikel 12 – Tystnadsplikt", "Artikel 12 – Tystnadsplikt"),
        _unit(
            "ny.docx",
            "12.1",
            "12.1 Sekretess",
            "12.1\tMottagande part ska hålla sekretess.\n",
        ),
        _unit("ny.docx", "", "III. Tystnadsplikt", "III. Tystnadsplikt\nTystnadsplikt.\n"),
    ]
    judged = assess_with_citation_labels(
        _trace(
            "ny.docx",
            [
                (
                    "classify",
                    "YES",
                    "Inget i denna punkt ska begränsa parts ansvar för brott mot artikel 12.\n",
                )
            ],
        ),
        catalog,
    )
    assert judged["examined_support"] == SUPPORTED
    assert judged["why"] == RESOLVED_AND_RELATED
    assert judged["investigation"] == INVESTIGATION_PARTIAL
    assert judged["does_not_change_relation_test"] is True
    roman = assess_with_citation_labels(
        _trace(
            "ny.docx",
            [
                (
                    "classify",
                    "YES",
                    "Begränsningen gäller inte för ansvar vid brott mot avsnitt III.\n",
                )
            ],
        ),
        catalog,
    )
    assert roman["examined_support"] == SUPPORTED


def test_finding_labeled_clause_is_not_admission() -> None:
    catalog = [_unit("ny.docx", "", "Artikel 12 – Utförande", "Artikel 12 – Utförande\nArbete.\n")]
    judged = assess_with_citation_labels(
        _trace(
            "ny.docx",
            [
                (
                    "classify",
                    "YES",
                    "Inget i denna punkt ska begränsa parts ansvar för brott mot artikel 12.\n",
                )
            ],
        ),
        catalog,
    )
    assert judged["examined_support"] == UNDECIDED
    assert judged["why"] == CITED_CLAUSE_NOT_RELATION


def test_missing_and_duplicate_labels_stay_undecided() -> None:
    missing = assess_with_citation_labels(
        _trace(
            "ny.docx",
            [("classify", "YES", "Begränsningen gäller inte för ansvar vid brott mot klausul 9.\n")],
        ),
        [_unit("ny.docx", "2", "2. Sekretess", "2. Sekretess\nTystnadsplikt.\n")],
    )
    assert missing["examined_support"] == UNDECIDED
    assert missing["label_lookups"][0]["status"] == ABSENT
    duplicate = [
        _unit("ny.docx", "4", "4. Avtalsföremål", "4. Avtalsföremål"),
        _unit("ny.docx", "4", "4. Tystnadsplikt", "4. Tystnadsplikt\nSekretess.\n"),
    ]
    judged = assess_with_citation_labels(
        _trace(
            "ny.docx",
            [("classify", "YES", "Begränsningen gäller inte för ansvar vid brott mot klausul 4.\n")],
        ),
        duplicate,
    )
    assert judged["examined_support"] == UNDECIDED
    assert judged["label_lookups"][0]["status"] == AMBIGUOUS


def test_higher_cap_and_wrong_clause_and_anaphor_remain() -> None:
    higher = assess_with_citation_labels(
        _trace(
            "avtal_120.docx",
            [
                (
                    "classify",
                    "YES",
                    "För skada till följd av brott mot artikel 7 gäller i stället "
                    "för begränsningen ovan en särskild högsta ersättning.\n",
                )
            ],
        ),
        [
            _unit("avtal_120.docx", "", "Artikel 7 – Skydd för information", "Artikel 7 – Skydd"),
            _unit(
                "avtal_120.docx",
                "7.1",
                "7.1 Förtrolig Information",
                "7.1\tFörtrolig Information ska hållas hemlig.\n",
            ),
        ],
    )
    assert higher["examined_support"] == UNDECIDED
    assert higher["why"] == CITED_CLAUSE_NOT_RELATION
    assert (
        assess_with_citation_labels(
            _trace("avtal_138.docx", [("classify", "YES", YES_138)]),
            CATALOG_138,
        )["why"]
        == CITED_CLAUSE_NOT_RELATION
    )
    judged = assess_with_citation_labels(
        _trace("avtal_103.docx", [("classify", "YES", YES_103)]),
        CATALOG_103,
    )
    assert judged["why"] == RESOLVED_AND_RELATED
    anaphor = assess_with_citation_labels(
        _seq_trace(
            "avtal_107.docx",
            [
                ("classify", "NO", "3. Sekretess och tystnadsplikt\n", 10),
                ("classify", "YES", YES_107, 22),
                ("navigation", "NO", HOP_107, 21),
            ],
        ),
        [],
    )
    assert anaphor["examined_support"] == SUPPORTED
    assert anaphor["why"] == "resolved_anaphor"


def test_leftover_five_and_baseline() -> None:
    payload = run_citation_labels()
    if payload["decisions"]:
        assert payload["delta"]["new_true_support"] == [
            "avtal_118.docx",
            "avtal_125.docx",
            "avtal_141.docx",
            "avtal_153.docx",
            "avtal_179.docx",
        ]
        assert payload["treatment"]["counts"]["false_approvals"] == 0
        assert payload["treatment"]["investigation_complete_from_proof"] is False
        assert payload["cases"]["avtal_120.docx"]["why"] == CITED_CLAUSE_NOT_RELATION
        assert payload["applied_to_v3"] is False
        assert freeze_citation_label_baseline(payload)["does_not_change_relation_test"] is True
    frozen = load_citation_label_baseline()
    assert frozen["applied_to_v3"] is False
    assert frozen["headline"]["delta"]["true_support"] == 5
    assert frozen["headline"]["treatment_counts"]["false_approvals"] == 0
    assert RETRIEVAL_CONCLUSIONS["citation_label_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["does_not_change_relation_test"] is True
