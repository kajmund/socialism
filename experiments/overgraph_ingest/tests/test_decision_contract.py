from overgraph_ingest.coverage.chain_contract import (
    EXISTING_LINK,
    OSKALIGT_NOT_CLAIM,
    SUPPORTED,
    UNDECIDED,
    UNHANDLED_AMENDMENT,
    UNRESOLVED_ANAPHOR,
    UNRESOLVED_CITATION,
    assess_chain,
    hop_always_decision,
)
from overgraph_ingest.coverage.chain_run import (
    freeze_decision_contract_baseline,
    run_decision_contract,
)
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_decision_contract_baseline,
)


def _trace(document_id: str, events: list[tuple[str, str, str]], *, found: bool = True) -> dict[str, object]:
    rows = []
    for index, (kind, predicted, text) in enumerate(events):
        rows.append(
            {
                "index": index,
                "kind": kind,
                "predicted": predicted,
                "text": text,
                "identity": {"key": f"{document_id}-{index}"},
            }
        )
    rows.append({"index": len(rows), "kind": "proof_decision", "status": "EVIDENCE_FOUND"})
    return {
        "document_id": document_id,
        "events": rows,
        "status": "EVIDENCE_FOUND" if found else "NO_EVIDENCE_YET",
        "why_evidence_found": "jev_yes_after_hop" if found else None,
    }


AMENDMENT_119 = (
    "1.1\tMed ändring av punkt 2.4 i Bilaga 2 gäller ansvarsbegränsningen "
    "även vid brott mot sekretess.\n"
)
YES_119 = "2.4\tBegränsningen ovan gäller inte heller vid brott mot punkt 1.\n"
HOP_119 = "2.3\tBegränsningen gäller inte vid uppsåt eller grov vårdslöshet.\n"
YES_103 = "5.3\tInget i denna punkt ska begränsa parts ansvar för brott mot avsnitt 4.\n"
HOP_103 = "5.2\tSkadestånd ska under avtalets hela löptid sammanlagt inte överstiga 2 500 000 kronor.\n"
YES_106 = (
    "Begränsningen i denna punkt ska inte tillämpas om skadan har orsakats "
    "uppsåtligen eller genom grov vårdslöshet.\n"
    "Detsamma gäller skada som uppkommer till följd av att part åsidosätter sin tystnadsplikt.\n"
)
YES_107 = "5.4\tSamma sak gäller för skada som orsakas av att part obehörigen röjer Förtrolig Information.\n"
HOP_107 = "5.3\tBegränsningarna i denna punkt ska inte tillämpas om skadan har orsakats uppsåtligen eller genom grov vårdslöshet.\n"
YES_113 = (
    "8.4\tBegränsningarna ovan gäller inte vid skada som har orsakats genom "
    "uppsåt eller grov vårdslöshet, och inte heller vid brott mot parts "
    "skyldigheter avseende Konfidentiell Information.\n"
)
YES_140 = (
    "7.3\tAnsvarsbegränsningen ovan gäller inte i följande fall:\n"
    "(c) skada till följd av obehörigt röjande av Förtrolig Information;\n"
)
YES_138 = "6.5\tBegränsningen gäller inte heller vid brott mot sekretessåtagandet i punkt 12.\n"
YES_142 = (
    "6.3\tBegränsningen ska inte tillämpas i den mån det skulle vara uppenbart "
    "oskäligt, varvid särskild hänsyn ska tas till om skadan har orsakats "
    "genom röjande av Konfidentiell Information.\n"
)
YES_173 = "6.4\tBegränsningen gäller inte heller vid brott mot sekretessåtagandet i punkt 8.\n"


def test_amendment_cases_stay_undecided() -> None:
    for path, yes in (("avtal_119.docx", YES_119), ("avtal_200.docx", YES_119)):
        trace = _trace(path, [("classify", "NO", AMENDMENT_119), ("classify", "YES", yes), ("navigation", "NO", HOP_119)])
        assert hop_always_decision(trace)["examined_support"] == SUPPORTED
        judged = assess_chain(trace)
        assert judged["examined_support"] == UNDECIDED
        assert judged["why"] == UNHANDLED_AMENDMENT
        assert judged["investigation"] == INVESTIGATION_PARTIAL


def test_unresolved_citation_is_not_any_hop() -> None:
    judged = assess_chain(
        _trace("avtal_103.docx", [("classify", "YES", YES_103), ("navigation", "NO", HOP_103)])
    )
    assert judged["examined_support"] == UNDECIDED
    assert judged["why"] == UNRESOLVED_CITATION
    assert "resolve_cited_material" in judged["navigation"]


def test_existing_link_does_not_need_hop() -> None:
    for path, text in (
        ("avtal_106.docx", YES_106),
        ("avtal_113.docx", YES_113),
        ("avtal_140.docx", YES_140),
    ):
        judged = assess_chain(_trace(path, [("classify", "YES", text)]))
        assert judged["examined_support"] == SUPPORTED
        assert judged["why"] == EXISTING_LINK
        assert judged["hop_attempted"] is False
        assert judged["investigation"] == INVESTIGATION_PARTIAL


def test_anaphor_is_not_proved_by_previous_hop() -> None:
    judged = assess_chain(
        _trace("avtal_107.docx", [("classify", "YES", YES_107), ("navigation", "NO", HOP_107)])
    )
    assert judged["examined_support"] == UNDECIDED
    assert judged["why"] == UNRESOLVED_ANAPHOR


def test_uncertain_cases_are_not_repaired() -> None:
    rows = (
        ("avtal_138.docx", YES_138, UNRESOLVED_CITATION),
        ("avtal_173.docx", YES_173, UNRESOLVED_CITATION),
        ("avtal_142.docx", YES_142, OSKALIGT_NOT_CLAIM),
    )
    for path, text, why in rows:
        judged = assess_chain(_trace(path, [("classify", "YES", text), ("navigation", "NO", HOP_119)]))
        assert judged["examined_support"] == UNDECIDED
        assert judged["why"] == why


def test_supported_does_not_become_complete() -> None:
    judged = assess_chain(_trace("avtal_106.docx", [("classify", "YES", YES_106)]))
    assert judged["examined_support"] == SUPPORTED
    assert judged["investigation"] == INVESTIGATION_PARTIAL
    assert judged["approved_chain_does_not_upgrade_investigation"] is True


def test_decision_contract_baseline() -> None:
    frozen = load_decision_contract_baseline()
    assert frozen["same_mapping_for_both_variants"] == "gold-map-v2"
    assert frozen["does_not_rewrite_history"] is True
    assert frozen["headline"]["reference_counts"]["false_approvals"] == 2
    assert frozen["headline"]["reference_counts"]["true_support"] == 39
    assert frozen["headline"]["treatment_counts"]["false_approvals"] == 0
    assert frozen["headline"]["treatment_counts"]["repaired_uncertain"] == 0
    assert frozen["headline"]["treatment_counts"]["true_support"] == 12
    assert frozen["headline"]["cases"]["avtal_119.docx"]["why"] == UNHANDLED_AMENDMENT
    assert frozen["headline"]["cases"]["avtal_103.docx"]["why"] == UNRESOLVED_CITATION
    assert frozen["headline"]["cases"]["avtal_107.docx"]["why"] == UNRESOLVED_ANAPHOR
    assert RETRIEVAL_CONCLUSIONS["same_mapping_for_both_variants"] == "gold-map-v2"
    assert RETRIEVAL_CONCLUSIONS["decision_contract_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["approved_chain_does_not_upgrade_investigation"] is True
    payload = run_decision_contract()
    assert payload["applied_to_v3"] is False
    if payload["decisions"]:
        assert payload["treatment"]["counts"]["false_approvals"] == 0
        assert payload["treatment"]["counts"]["true_support"] == 12
        assert payload["treatment"]["investigation_complete_from_proof"] is False
        assert freeze_decision_contract_baseline(payload)["applied_to_v3"] is False
