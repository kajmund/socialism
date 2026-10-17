"""Hand diagnosis of the 34 leftover gold YES after anaphor-list. No new Jev."""

from __future__ import annotations

from collections import Counter

PARAPHRASE = "paraphrase"
AMENDMENT = "amendment"
RANKING = "document_ranking"
DEFINED_TERM = "defined_term"
OTHER_LINK = "other_unresolved_link"
CLASS_ORDER = (PARAPHRASE, AMENDMENT, RANKING, DEFINED_TERM, OTHER_LINK)

COVERAGE = "coverage"
EXCEPTION_PARAPHRASE = "exception_paraphrase"
CITATION_LABEL = "citation_label"
CLAUSE_NUMBERING = "clause_numbering"
DEFINED_TERMS = "defined_terms"
HEADING_REFERENCE = "heading_reference"
AMENDMENT_HANDLING = "amendment"
DOCUMENT_RANKING = "document_ranking"

QUALITY_REFERENCE = {
    "true_support": 19,
    "expected_yes": 53,
    "false_approvals": 0,
    "leftover_genuine": 34,
    "source": "phase2-anaphor-list-v1",
}


def _row(
    examined: bool,
    classes: tuple[str, ...],
    blocking: str,
    also_needs: tuple[str, ...],
    decidable_by_one: bool,
    note: str,
) -> dict[str, object]:
    return {
        "examined": examined,
        "classes": classes,
        "blocking_ability": blocking,
        "also_needs": also_needs,
        "decidable_by_one": decidable_by_one,
        "note": note,
    }


# One row per leftover gold YES. classes are multi-label. blocking_ability is
# the next missing ability. decidable_by_one is true only if that ability alone
# would make the examined chain assessable.
ROWS: dict[str, dict[str, object]] = {
    "avtal_105.docx": _row(
        True, (DEFINED_TERM, OTHER_LINK), HEADING_REFERENCE, (), True,
        "Hop already fetched Skydd för information; heading/defined term not linked",
    ),
    "avtal_111.docx": _row(
        False, (OTHER_LINK, RANKING), COVERAGE, (CITATION_LABEL, DOCUMENT_RANKING), False,
        "Huvudavtal ranking plus citation; never examined",
    ),
    "avtal_114.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (CITATION_LABEL,), False,
        "Avsnitt citation; never examined",
    ),
    "avtal_118.docx": _row(
        True, (OTHER_LINK,), CITATION_LABEL, (), True,
        "Artikel 4 is Tystnadsplikt; label not parsed",
    ),
    "avtal_120.docx": _row(
        True, (PARAPHRASE, OTHER_LINK), CITATION_LABEL, (EXCEPTION_PARAPHRASE,), False,
        "Higher cap for artikel 7; needs label and paraphrase",
    ),
    "avtal_121.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (CITATION_LABEL,), False,
        "List plus klausul 7; never examined",
    ),
    "avtal_125.docx": _row(
        True, (OTHER_LINK,), CITATION_LABEL, (), True,
        "Roman VIII.2 / avsnitt VI",
    ),
    "avtal_127.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (CITATION_LABEL,), False,
        "List plus punkt 5; never examined",
    ),
    "avtal_129.docx": _row(
        True, (DEFINED_TERM,), DEFINED_TERMS, (), True,
        "Gäller inte Skyddad Information in-unit",
    ),
    "avtal_130.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (CITATION_LABEL,), False,
        "Punkt citation; never examined",
    ),
    "avtal_134.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Omfattar inte sekretessåtagandet",
    ),
    "avtal_135.docx": _row(
        False, (), COVERAGE, (), True,
        "Detsamma plus tystnadsplikt; current anaphor would admit if found",
    ),
    "avtal_137.docx": _row(
        True, (PARAPHRASE, OTHER_LINK), CLAUSE_NUMBERING, (EXCEPTION_PARAPHRASE,), False,
        "§ 5 is in the title; also higher-cap paraphrase",
    ),
    "avtal_141.docx": _row(
        True, (OTHER_LINK,), CITATION_LABEL, (), True,
        "Klausul 6 is Sekretess",
    ),
    "avtal_153.docx": _row(
        True, (OTHER_LINK,), CITATION_LABEL, (), True,
        "Klausul 5 uniquely titles Hantering av konfidentiell information",
    ),
    "avtal_155.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (CITATION_LABEL,), False,
        "Anaphor plus artikel 7; never examined",
    ),
    "avtal_157.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Avsnitt 9 resolved to Sekretess; source is higher cap",
    ),
    "avtal_158.docx": _row(
        False, (AMENDMENT, RANKING), COVERAGE, (AMENDMENT_HANDLING, DOCUMENT_RANKING), False,
        "Med ändring av Bilaga 2; never examined",
    ),
    "avtal_159.docx": _row(
        False, (), COVERAGE, (), True,
        "Gäller inte konfidentiell information; existing_link if found",
    ),
    "avtal_160.docx": _row(
        False, (OTHER_LINK, RANKING), COVERAGE, (CLAUSE_NUMBERING, DOCUMENT_RANKING), False,
        "Marked Alternativ A plus § citation; never examined",
    ),
    "avtal_161.docx": _row(
        True, (OTHER_LINK,), CLAUSE_NUMBERING, (), True,
        "Detsamma plus § 3 Sekretess; empty clause_number",
    ),
    "avtal_163.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Omfattar inte sekretessåtagandet",
    ),
    "avtal_168.docx": _row(
        False, (), COVERAGE, (), True,
        "Detsamma plus tystnadsplikt; current anaphor would admit if found",
    ),
    "avtal_169.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (CITATION_LABEL,), False,
        "Artikel citation; never examined",
    ),
    "avtal_172.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Omfattar inte sekretessåtagandet",
    ),
    "avtal_179.docx": _row(
        True, (OTHER_LINK,), CITATION_LABEL, (), True,
        "Klausul 7 is Hantering av konfidentiell information",
    ),
    "avtal_180.docx": _row(
        True, (RANKING, OTHER_LINK), DOCUMENT_RANKING, (), True,
        "Two punkt 1: Avtalsföremål versus Tystnadsplikt",
    ),
    "avtal_181.docx": _row(
        False, (AMENDMENT, RANKING), COVERAGE, (AMENDMENT_HANDLING, DOCUMENT_RANKING), False,
        "Med ändring av Bilaga 2; never examined",
    ),
    "avtal_184.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Omfattar inte sekretessåtagandet",
    ),
    "avtal_190.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Omfattar inte sekretessåtagandet",
    ),
    "avtal_192.docx": _row(
        True, (OTHER_LINK,), CLAUSE_NUMBERING, (), True,
        "§ 3 is in the title; empty clause_number",
    ),
    "avtal_193.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Double-negation paraphrase plus tystnadsplikt in-unit",
    ),
    "avtal_194.docx": _row(
        True, (PARAPHRASE, OTHER_LINK), CITATION_LABEL, (EXCEPTION_PARAPHRASE,), False,
        "Higher cap plus artikel 5; needs label and paraphrase",
    ),
    "avtal_196.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (CLAUSE_NUMBERING,), False,
        "§ citation; never examined",
    ),
}


def summarize(rows: dict[str, dict[str, object]] | None = None) -> dict[str, object]:
    table = rows or ROWS
    examined = [path for path, row in table.items() if row["examined"]]
    unexamined = [path for path, row in table.items() if not row["examined"]]
    class_docs = {name: [] for name in CLASS_ORDER}
    for path, row in table.items():
        for name in row["classes"]:
            class_docs[name].append(path)
    blocking = Counter(str(row["blocking_ability"]) for row in table.values())
    one = [
        path
        for path, row in table.items()
        if row["examined"] and row["decidable_by_one"]
    ]
    one_by = Counter(str(table[path]["blocking_ability"]) for path in one)
    coverage_only = [
        path
        for path, row in table.items()
        if not row["examined"] and row["decidable_by_one"]
    ]
    one_docs = {
        name: sorted(path for path in one if table[path]["blocking_ability"] == name)
        for name in one_by
    }
    return {
        "leftover": len(table),
        "examined": len(examined),
        "unexamined": len(unexamined),
        "documents_per_class": {name: len(class_docs[name]) for name in CLASS_ORDER},
        "class_documents": {name: sorted(class_docs[name]) for name in CLASS_ORDER},
        "blocking_ability_counts": dict(blocking),
        "decidable_by_one_examined": dict(one_by),
        "decidable_by_one_examined_documents": sorted(one),
        "ranked_unlock_if_one_ability": [
            {"ability": name, "count": count, "documents": one_docs[name]}
            for name, count in one_by.most_common()
        ],
        "unlocks_if_examined_with_current_abilities": sorted(coverage_only),
        "quality_reference": QUALITY_REFERENCE,
        "same_document_may_have_several_classes": True,
        "does_not_choose_next_ability": True,
    }


def public_rows(
    observed_why: dict[str, str | None] | None = None,
) -> dict[str, dict[str, object]]:
    why = observed_why or {}
    return {
        path: {
            "examined": row["examined"],
            "classes": list(row["classes"]),
            "blocking_ability": row["blocking_ability"],
            "also_needs": list(row["also_needs"]),
            "decidable_by_one": row["decidable_by_one"],
            "note": row["note"],
            "observed_why": why.get(path),
        }
        for path, row in ROWS.items()
    }
