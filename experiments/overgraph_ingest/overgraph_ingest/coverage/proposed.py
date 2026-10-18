"""Why a proposed predicate is not verified. No new Jev. Not a looser rule."""

from __future__ import annotations

import re

PARAPHRASE = "paraphrase_without_operator"
OTHER_RELATION = "other_legal_relation"
MISSING_SPAN = "missing_relation_in_span"
INCOMPLETE_REFERENCE = "incomplete_reference"
AMBIGUOUS = "ambiguous_wording"
CAUSES = (PARAPHRASE, OTHER_RELATION, MISSING_SPAN, INCOMPLETE_REFERENCE, AMBIGUOUS)
POINTER_RE = re.compile(r"\b(?:punkt|klausul)\s+\d", re.I)

def _item(
    case_id: str,
    phase: str,
    group: str,
    operator: str,
    excerpt: str,
    reason: str,
) -> dict[str, str]:
    return {
        "id": case_id,
        "phase": phase,
        "group": group,
        "operator": operator,
        "excerpt": excerpt,
        "reason": reason,
    }


PROPOSED_ROWS = (
    _item("synonym_ansvarstak_tystnadsplikt", "before", "synonym", "does_not_apply",
          "Ansvarstaket ska inte tillämpas på överträdelser av tystnadsplikten.",
          "paraphrase_unverified"),
    _item("synonym_rojande_konfidentiell", "before", "synonym", "does_not_apply",
          "Skador till följd av röjande av konfidentiell information omfattas inte av ansvarsbegränsningen.",
          "paraphrase_unverified"),
    _item("synonym_obegransat", "before", "synonym", "does_not_apply",
          "Parternas ansvar för brott mot sekretessåtagandet är obegränsat.",
          "paraphrase_unverified"),
    _item("synonym_tystnadsplikt", "before", "synonym", "does_not_apply",
          "Begränsningen gäller inte vid brott mot tystnadsplikten.",
          "paraphrase_unverified"),
    _item("synonym_konfidentiell_gilt", "before", "synonym", "does_not_apply",
          "Ansvarsbegränsningen gäller inte vid röjande av konfidentiell information.",
          "paraphrase_unverified"),
    _item("synonym_undantas", "before", "synonym", "does_not_apply",
          "Brott mot sekretess undantas från ansvarsbegränsningen.",
          "paraphrase_unverified"),
    _item("synonym_inte_tillamplig", "before", "synonym", "does_not_apply",
          "Ansvarsbegränsningen är inte tillämplig på sekretessbrott.",
          "paraphrase_unverified"),
    _item("negation_gäller_även", "before", "negation", "applies",
          "Ansvarsbegränsningen gäller även vid brott mot sekretessförpliktelserna.",
          "applies_unverified"),
    _item("negation_gäller_också", "before", "negation", "applies",
          "Ansvarstaket gäller också vid sekretessbrott.",
          "applies_unverified"),
    _item("negation_gäller_utan_inte", "before", "negation", "applies",
          "Ansvarsbegränsningen gäller vid brott mot sekretessförpliktelserna.",
          "applies_unverified"),
    _item("negation_tillampas_aven", "before", "negation", "applies",
          "Ansvarsbegränsningen ska tillämpas även vid brott mot sekretess.",
          "applies_unverified"),
    _item("negation_inget_undantag", "before", "negation", "applies",
          "Inget undantag görs för sekretessbrott från ansvarsbegränsningen.",
          "applies_unverified"),
    _item("negation_endast_uppsat", "before", "negation", "applies",
          "Endast uppsåt och grov vårdslöshet undantas från ansvarsbegränsningen, inte sekretessbrott.",
          "applies_unverified"),
    _item("negation_dock_vid", "before", "negation", "applies",
          "Begränsningen gäller dock vid brott mot sekretess.",
          "applies_unverified"),
    _item("reference_punkt_8_secrecy", "after", "reference", "does_not_apply",
          "Begränsningen gäller inte vid överträdelser av punkt 8.",
          "paraphrase_unverified"),
    _item("reference_abc_verify_c", "after", "reference", "does_not_apply",
          "Begränsningen gäller inte vid överträdelse av punkt 3.",
          "paraphrase_unverified"),
    _item("cooccurrence_abc_then_link", "after", "cooccurrence", "does_not_apply",
          "Begränsningen gäller inte vid överträdelse av punkt 3.",
          "paraphrase_unverified"),
)


def classify_proposed(row: dict[str, str]) -> dict[str, object]:
    """More hops do not turn these into verified claim proofs."""
    if row["operator"] == "applies":
        cause = OTHER_RELATION
    elif POINTER_RE.search(row["excerpt"] or ""):
        cause = MISSING_SPAN if row.get("phase") == "after" else INCOMPLETE_REFERENCE
    else:
        cause = PARAPHRASE
    return {
        "id": row["id"],
        "phase": row["phase"],
        "group": row["group"],
        "operator": row["operator"],
        "excerpt": row["excerpt"],
        "reason": row["reason"],
        "cause": cause,
        "more_information_can_verify": False,
        "supports_claim": False,
        "should_stay_undecided": True,
    }
