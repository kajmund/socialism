"""Metamorphic clause variations. Does not change the link detector or v3."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.proof_link import (
    LINKED_RELATION,
    evaluate_passage,
    evaluate_passages,
    resolve_reference,
)

MORPH_BASELINE_ID = "phase2-proof-morph-v1"
MORPH_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{MORPH_BASELINE_ID}.json"
)
GROUPS = ("synonym", "negation", "reference", "cooccurrence")
EVEN_CASE = "negation_gäller_även"
INTE_CASE = "negation_gäller_inte_control"


def _case(
    case_id: str,
    group: str,
    property_name: str,
    expected: str,
    *texts: str,
    navigate: tuple[int, int] | None = None,
    expected_after: str | None = None,
) -> dict[str, object]:
    return {
        "id": case_id,
        "group": group,
        "property": property_name,
        "texts": list(texts),
        "expected": expected,
        "navigate": None if navigate is None else list(navigate),
        "expected_after": expected_after,
    }


CASES: tuple[dict[str, object], ...] = (
    # Synonyms: same legal link, other words. Expected linked.
    _case("synonym_seed", "synonym", "semantic_invariance", LINKED_RELATION,
          "Ansvarsbegränsningen gäller inte vid brott mot sekretessförpliktelserna."),
    _case("synonym_ansvarstak_tystnadsplikt", "synonym", "semantic_invariance", LINKED_RELATION,
          "Ansvarstaket ska inte tillämpas på överträdelser av tystnadsplikten."),
    _case("synonym_rojande_konfidentiell", "synonym", "semantic_invariance", LINKED_RELATION,
          "Skador till följd av röjande av konfidentiell information omfattas inte av ansvarsbegränsningen."),
    _case("synonym_obegransat", "synonym", "semantic_invariance", LINKED_RELATION,
          "Parternas ansvar för brott mot sekretessåtagandet är obegränsat."),
    _case("synonym_tystnadsplikt", "synonym", "semantic_invariance", LINKED_RELATION,
          "Begränsningen gäller inte vid brott mot tystnadsplikten."),
    _case("synonym_konfidentiell_gilt", "synonym", "semantic_invariance", LINKED_RELATION,
          "Ansvarsbegränsningen gäller inte vid röjande av konfidentiell information."),
    _case("synonym_overtradelse", "synonym", "semantic_invariance", LINKED_RELATION,
          "Ansvarstaket gäller inte vid överträdelse av sekretessåtagandet."),
    _case("synonym_undantas", "synonym", "semantic_invariance", LINKED_RELATION,
          "Brott mot sekretess undantas från ansvarsbegränsningen."),
    _case("synonym_inte_tillamplig", "synonym", "semantic_invariance", LINKED_RELATION,
          "Ansvarsbegränsningen är inte tillämplig på sekretessbrott."),
    _case("synonym_taket", "synonym", "semantic_invariance", LINKED_RELATION,
          "Taket för skadestånd gäller inte vid brott mot sekretess."),
    # Negations: flip or remove the carve-out.
    _case(EVEN_CASE, "negation", "negation_sensitivity", "not_grounded",
          "Ansvarsbegränsningen gäller även vid brott mot sekretessförpliktelserna."),
    _case("negation_gäller_också", "negation", "negation_sensitivity", "not_grounded",
          "Ansvarstaket gäller också vid sekretessbrott."),
    _case("negation_gäller_utan_inte", "negation", "negation_sensitivity", "not_grounded",
          "Ansvarsbegränsningen gäller vid brott mot sekretessförpliktelserna."),
    _case("negation_split_same_unit", "negation", "negation_sensitivity", "not_grounded",
          "Ansvarsbegränsningen gäller inte vid grov vårdslöshet. Sekretess regleras separat."),
    _case("negation_tillampas_aven", "negation", "negation_sensitivity", "not_grounded",
          "Ansvarsbegränsningen ska tillämpas även vid brott mot sekretess."),
    _case("negation_inget_undantag", "negation", "negation_sensitivity", "not_grounded",
          "Inget undantag görs för sekretessbrott från ansvarsbegränsningen."),
    _case(INTE_CASE, "negation", "negation_sensitivity", LINKED_RELATION,
          "Ansvarsbegränsningen gäller inte vid sekretessbrott."),
    _case("negation_endast_uppsat", "negation", "negation_sensitivity", "not_grounded",
          "Endast uppsåt och grov vårdslöshet undantas från ansvarsbegränsningen, inte sekretessbrott."),
    _case("negation_gäller_inte_utom_sekretess", "negation", "negation_sensitivity", "not_grounded",
          "Ansvarsbegränsningen gäller inte, utom vid sekretessbrott."),
    _case("negation_dock_vid", "negation", "negation_sensitivity", "not_grounded",
          "Begränsningen gäller dock vid brott mot sekretess."),
    # References: direct link versus clause pointer.
    _case("reference_punkt_8", "reference", "reference_resolution", "needs_navigation",
          "Begränsningen gäller inte vid överträdelser av punkt 8."),
    _case("reference_punkt_4", "reference", "reference_resolution", "needs_navigation",
          "Ansvarsbegränsningen gäller inte vid brott mot punkt 4."),
    _case("reference_punkt_4_infosec", "reference", "reference_resolution", "needs_navigation",
          "Ansvarsbegränsningen gäller inte vid brott mot punkt 4.",
          "4. Informationssäkerhet och dataskydd",
          navigate=(0, 1), expected_after="not_grounded"),
    _case("reference_punkt_8_secrecy", "reference", "reference_resolution", "needs_navigation",
          "Begränsningen gäller inte vid överträdelser av punkt 8.",
          "8. Sekretess och tystnadsplikt",
          navigate=(0, 1), expected_after=LINKED_RELATION),
    _case("reference_punkt_8_wrong", "reference", "reference_resolution", "needs_navigation",
          "Begränsningen gäller inte vid överträdelser av punkt 8.",
          "11. Sekretess och personuppgifter",
          navigate=(0, 1), expected_after="not_grounded"),
    _case("reference_direct", "reference", "reference_resolution", LINKED_RELATION,
          "Begränsningen gäller inte vid brott mot sekretess."),
    _case("reference_inline_and_punkt", "reference", "reference_resolution", LINKED_RELATION,
          "Begränsningen gäller inte vid överträdelse av sekretessförpliktelserna enligt punkt 3."),
    _case("reference_klausul", "reference", "reference_resolution", "needs_navigation",
          "Begränsningen gäller inte vid överträdelser av klausul 9."),
    _case("reference_punkt_12", "reference", "reference_resolution", "needs_navigation",
          "Begränsningen gäller inte vid punkt 12."),
    _case("reference_abc_verify_c", "reference", "reference_resolution", "needs_navigation",
          "Leverantörens sammanlagda skadeståndsansvar är begränsat till 500 000 kronor.",
          "Begränsningen gäller inte vid överträdelse av punkt 3.",
          "3. Parterna ska behandla all konfidentiell information med sekretess.",
          navigate=(1, 2), expected_after=LINKED_RELATION),
    # Co-occurrence: same keywords, no link — then one relation change.
    _case("cooccurrence_split_units", "cooccurrence", "structural_invariance", "not_grounded",
          "Ansvarsbegränsningen gäller inte vid grov vårdslöshet.",
          "Sekretess regleras separat."),
    _case("cooccurrence_abc", "cooccurrence", "structural_invariance", "not_grounded",
          "Leverantörens sammanlagda skadeståndsansvar är begränsat till 500 000 kronor.",
          "Begränsningen gäller inte vid uppsåt eller grov vårdslöshet.",
          "Parterna ska behandla all konfidentiell information med sekretess."),
    _case("cooccurrence_abc_then_link", "cooccurrence", "structural_invariance", "needs_navigation",
          "Leverantörens sammanlagda skadeståndsansvar är begränsat till 500 000 kronor.",
          "Begränsningen gäller inte vid överträdelse av punkt 3.",
          "3. Parterna ska behandla all konfidentiell information med sekretess.",
          navigate=(1, 2), expected_after=LINKED_RELATION),
    _case("cooccurrence_heading", "cooccurrence", "structural_invariance", "not_grounded",
          "Begränsningarna gäller inte vid uppsåt eller grov vårdslöshet.",
          "8. Sekretess"),
    _case("cooccurrence_keep_link", "cooccurrence", "structural_invariance", LINKED_RELATION,
          "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretess.",
          "13. Övrigt"),
    _case("cooccurrence_move_heading", "cooccurrence", "structural_invariance", LINKED_RELATION,
          "12.4 Begränsningarna gäller inte vid brott mot sekretess.",
          "8. Sekretess"),
    _case("cooccurrence_three_keywords", "cooccurrence", "structural_invariance", "not_grounded",
          "Ansvaret är begränsat till 500 000 kronor.",
          "Undantag gäller inte vid uppsåt.",
          "9. Sekretess"),
    _case("cooccurrence_avtal37", "cooccurrence", "structural_invariance", "not_grounded",
          "Begränsningarna gäller inte vid uppsåt eller grov vårdslöshet.",
          "8. Sekretess"),
    _case("cooccurrence_only_b_changed", "cooccurrence", "structural_invariance", "not_grounded",
          "Leverantörens sammanlagda skadeståndsansvar är begränsat till 500 000 kronor.",
          "Begränsningen gäller inte vid uppsåt eller grov vårdslöshet.",
          "Parterna ska behandla all konfidentiell information med sekretess."),
    _case("cooccurrence_false_then_true", "cooccurrence", "structural_invariance", LINKED_RELATION,
          "Leverantörens sammanlagda skadeståndsansvar är begränsat till 500 000 kronor.",
          "Begränsningen gäller inte vid överträdelse av sekretessförpliktelserna enligt punkt 3.",
          "3. Parterna ska behandla all konfidentiell information med sekretess."),
)


def judge_case(case: dict[str, object]) -> dict[str, object]:
    texts = [str(item) for item in case["texts"]]
    before = evaluate_passage(texts[0]) if len(texts) == 1 else evaluate_passages(texts)
    after = None
    nav = case.get("navigate")
    if nav:
        source, target = int(nav[0]), int(nav[1])
        after = resolve_reference(texts[source], texts[target])
    before_ok = before["status"] == case["expected"]
    after_expected = case.get("expected_after")
    after_ok = after is None or after_expected is None or after["status"] == after_expected
    return {
        "id": case["id"],
        "group": case["group"],
        "property": case["property"],
        "expected": case["expected"],
        "observed": before["status"],
        "pass": before_ok and after_ok,
        "cooccurrence_only": before.get("cooccurrence_only"),
        "expected_after": after_expected,
        "observed_after": None if after is None else after["status"],
        "after_pass": None if after_expected is None else after_ok,
        "false_complete": case["expected"] != LINKED_RELATION and before["status"] == LINKED_RELATION,
    }


def run_proof_morph() -> dict[str, object]:
    rows = [judge_case(case) for case in CASES]
    by_group = {name: [row for row in rows if row["group"] == name] for name in GROUPS}
    false_complete = [row["id"] for row in rows if row["false_complete"]]
    misses = [row["id"] for row in rows if not row["pass"]]
    even = next(row for row in rows if row["id"] == EVEN_CASE)
    inte = next(row for row in rows if row["id"] == INTE_CASE)
    even_vs_inte = even["observed"] != inte["observed"] and even["pass"] and inte["pass"]
    synonym = by_group["synonym"]
    return {
        "operation": "coverage",
        "experiment": "proof_morph_v1",
        "coverage_v3_unchanged": True,
        "does_not_replace_c8": True,
        "detector_unchanged": True,
        "not_an_independent_blind_test": True,
        "case_count": len(rows),
        "passed": sum(1 for row in rows if row["pass"]),
        "failed": misses,
        "false_complete": false_complete,
        "false_complete_count": len(false_complete),
        "synonym_recall": _recall(synonym, LINKED_RELATION),
        "negation_false_complete": sum(1 for row in by_group["negation"] if row["false_complete"]),
        "reference_identified": _recall(by_group["reference"], "needs_navigation"),
        "even_versus_inte": {
            "distinguishes": even_vs_inte,
            "even": even["observed"],
            "inte": inte["observed"],
        },
        "groups": {
            name: {
                "count": len(group),
                "passed": sum(1 for row in group if row["pass"]),
                "failed": [row["id"] for row in group if not row["pass"]],
            }
            for name, group in by_group.items()
        },
        "cases": rows,
    }


def freeze_proof_morph_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": MORPH_BASELINE_ID,
        "label": (
            "Frozen: metamorphic clause variations against the unchanged "
            "link detector. Not a blind corpus and not applied to v3."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "detector_unchanged": True,
        "not_an_independent_blind_test": True,
        "headline": {
            "case_count": payload.get("case_count"),
            "passed": payload.get("passed"),
            "failed_count": len(payload.get("failed") or []),
            "false_complete_count": payload.get("false_complete_count"),
            "synonym_recall": payload.get("synonym_recall"),
            "negation_false_complete": payload.get("negation_false_complete"),
            "even_versus_inte": payload.get("even_versus_inte"),
            "failed": payload.get("failed"),
        },
        "groups": payload.get("groups"),
    }


def write_proof_morph_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or MORPH_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_proof_morph_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_proof_morph_baseline(path: Path | None = None) -> dict[str, object]:
    return json.loads((path or MORPH_BASELINE_PATH).read_text(encoding="utf-8"))


def _recall(rows: list[dict[str, object]], expected: str) -> float:
    wanted = [row for row in rows if row["expected"] == expected]
    if not wanted:
        return 0.0
    return sum(1 for row in wanted if row["observed"] == expected) / len(wanted)
