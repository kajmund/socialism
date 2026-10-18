"""Diagnosis of the 29 leftover gold YES after citation labels. No new rules."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.citation_run import run_citation_labels
from overgraph_ingest.coverage.leftover_diagnosis import (
    AMENDMENT,
    AMENDMENT_HANDLING,
    CLAUSE_NUMBERING,
    COVERAGE,
    DEFINED_TERM,
    DEFINED_TERMS,
    DOCUMENT_RANKING,
    EXCEPTION_PARAPHRASE,
    HEADING_REFERENCE,
    OTHER_LINK,
    PARAPHRASE,
    RANKING,
    _row,
)
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION

ROOT = Path(__file__).resolve().parents[2]
LEFTOVER_29_ID = "phase2-leftover-29-v1"
LEFTOVER_29_PATH = ROOT / "baselines" / f"{LEFTOVER_29_ID}.json"

HIGHER_CAP = "higher_cap"
DOUBLE_NEGATION = "double_negation"
SEMANTIC = "semantic_understanding"
DISCOVERY = "discovery"
STRUCTURE = "remaining_structure"

QUALITY_REFERENCE = {
    "true_support": 24,
    "expected_yes": 53,
    "false_approvals": 0,
    "leftover_genuine": 29,
    "source": "phase2-citation-label-v1",
}

REMOVED_BY_CITATION_LABELS = (
    "avtal_118.docx",
    "avtal_125.docx",
    "avtal_141.docx",
    "avtal_153.docx",
    "avtal_179.docx",
)

ROWS: dict[str, dict[str, object]] = {
    "avtal_105.docx": _row(
        True, (DEFINED_TERM, OTHER_LINK), HEADING_REFERENCE, (), True,
        "Hop already fetched Skydd för information",
    ),
    "avtal_111.docx": _row(
        False, (OTHER_LINK, RANKING), COVERAGE, (DOCUMENT_RANKING,), False,
        "Huvudavtal ranking plus citation; never examined",
    ),
    "avtal_114.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (), False,
        "Avsnitt citation; never examined",
    ),
    "avtal_120.docx": _row(
        True, (PARAPHRASE,), HIGHER_CAP, (), True,
        "Artikel 7 unique; source is higher cap",
    ),
    "avtal_121.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (), False,
        "List plus klausul 7; never examined",
    ),
    "avtal_127.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (), False,
        "List plus punkt 5; never examined",
    ),
    "avtal_129.docx": _row(
        True, (DEFINED_TERM,), DEFINED_TERMS, (), True,
        "Gäller inte Skyddad Information in-unit",
    ),
    "avtal_130.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (), False,
        "Punkt citation; never examined",
    ),
    "avtal_134.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Omfattar inte sekretessåtagandet",
    ),
    "avtal_135.docx": _row(
        False, (), COVERAGE, (), True,
        "Current anaphor would admit if found",
    ),
    "avtal_137.docx": _row(
        True, (PARAPHRASE, OTHER_LINK), CLAUSE_NUMBERING, (HIGHER_CAP,), False,
        "§ 5 in the title; also higher-cap paraphrase",
    ),
    "avtal_155.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (), False,
        "Anaphor plus artikel 7; never examined",
    ),
    "avtal_157.docx": _row(
        True, (PARAPHRASE,), HIGHER_CAP, (), True,
        "Avsnitt 9 unique; source is higher cap",
    ),
    "avtal_158.docx": _row(
        False, (AMENDMENT, RANKING), COVERAGE, (AMENDMENT_HANDLING, DOCUMENT_RANKING), False,
        "Med ändring av Bilaga 2; never examined",
    ),
    "avtal_159.docx": _row(
        False, (), COVERAGE, (), True,
        "Existing in-unit link if found",
    ),
    "avtal_160.docx": _row(
        False, (OTHER_LINK, RANKING), COVERAGE, (CLAUSE_NUMBERING, DOCUMENT_RANKING), False,
        "Marked Alternativ A plus § citation; never examined",
    ),
    "avtal_161.docx": _row(
        True, (OTHER_LINK,), CLAUSE_NUMBERING, (), True,
        "§ 3 Sekretess; empty clause_number",
    ),
    "avtal_163.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Omfattar inte sekretessåtagandet",
    ),
    "avtal_168.docx": _row(
        False, (), COVERAGE, (), True,
        "Current anaphor would admit if found",
    ),
    "avtal_169.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (), False,
        "Artikel citation; never examined",
    ),
    "avtal_172.docx": _row(
        True, (PARAPHRASE,), EXCEPTION_PARAPHRASE, (), True,
        "Omfattar inte sekretessåtagandet",
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
        "§ 3 in the title; empty clause_number",
    ),
    "avtal_193.docx": _row(
        True, (PARAPHRASE,), DOUBLE_NEGATION, (), True,
        "Double-negation paraphrase plus tystnadsplikt in-unit",
    ),
    "avtal_194.docx": _row(
        True, (PARAPHRASE,), HIGHER_CAP, (), True,
        "Artikel 5 unique; source is higher cap",
    ),
    "avtal_196.docx": _row(
        False, (OTHER_LINK,), COVERAGE, (CLAUSE_NUMBERING,), False,
        "§ citation; never examined",
    ),
}

SEMANTIC_BLOCKS = frozenset(
    {EXCEPTION_PARAPHRASE, HIGHER_CAP, DOUBLE_NEGATION, DEFINED_TERMS}
)
STRUCTURE_BLOCKS = frozenset({HEADING_REFERENCE, CLAUSE_NUMBERING, DOCUMENT_RANKING})


def summarize(rows: dict[str, dict[str, object]] | None = None) -> dict[str, object]:
    table = rows or ROWS
    examined = sorted(path for path, row in table.items() if row["examined"])
    unexamined = sorted(path for path, row in table.items() if not row["examined"])
    semantic = sorted(
        path
        for path, row in table.items()
        if row["examined"]
        and row["blocking_ability"] in SEMANTIC_BLOCKS
        and row["decidable_by_one"]
    )
    structure = sorted(
        path
        for path, row in table.items()
        if row["examined"]
        and row["blocking_ability"] in STRUCTURE_BLOCKS
        and row["decidable_by_one"]
    )
    both = sorted(
        path
        for path, row in table.items()
        if row["examined"] and not row["decidable_by_one"]
    )
    current_if_found = sorted(
        path
        for path, row in table.items()
        if not row["examined"] and row["decidable_by_one"]
    )
    return {
        "leftover": len(table),
        "examined": len(examined),
        "unexamined": len(unexamined),
        "tracks": {
            SEMANTIC: {"count": len(semantic), "documents": semantic},
            DISCOVERY: {"count": len(unexamined), "documents": unexamined},
            STRUCTURE: {"count": len(structure), "documents": structure},
            "needs_two_abilities": {"count": len(both), "documents": both},
        },
        "unlocks_if_examined_with_current_abilities": current_if_found,
        "removed_by_citation_labels": list(REMOVED_BY_CITATION_LABELS),
        "quality_reference": QUALITY_REFERENCE,
        "does_not_choose_next_ability": True,
        "does_not_add_another_parser_rule": True,
        "fork_is_semantics_versus_discovery": True,
    }


def run_leftover_29(
    *,
    path: Path | None = None,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
) -> dict[str, object]:
    payload = run_citation_labels(
        path=path, db_path=db_path, dense_dimension=dense_dimension
    )
    live = None
    observed: dict[str, str | None] = {}
    if payload["decisions"]:
        live = list(payload["treatment"]["leftover_genuine"])
        if set(live) != set(ROWS):
            raise ValueError(
                "live leftover 29 does not match table: "
                f"missing={sorted(set(live) - set(ROWS))} "
                f"extra={sorted(set(ROWS) - set(live))}"
            )
        by_id = {str(row["document_id"]): row for row in payload["decisions"]}
        for document_id in ROWS:
            judged = by_id.get(document_id)
            observed[document_id] = None if judged is None else judged.get("why")
    return {
        "operation": "diagnosis",
        "experiment": "leftover_29_v1",
        "applied_to_v3": False,
        "no_new_jev": True,
        "does_not_start_next_ability": True,
        "does_not_add_another_parser_rule": True,
        "same_mapping": GOLD_MAP_VERSION,
        "quality_reference": QUALITY_REFERENCE,
        "summary": summarize(),
        "rows": {
            path: {
                **{key: list(value) if isinstance(value, tuple) else value for key, value in row.items()},
                "observed_why": observed.get(path),
            }
            for path, row in ROWS.items()
        },
        "live_leftover": live,
        "live_leftover_matches_table": live is None or set(live) == set(ROWS),
    }


def freeze_leftover_29(payload: dict[str, object] | None = None) -> dict[str, object]:
    body = payload or run_leftover_29()
    return {
        "id": LEFTOVER_29_ID,
        "label": (
            "Frozen: 15 examined and 14 unexamined leftover YES after "
            "citation labels. Fork is semantics versus discovery. "
            "Does not start the next ability. 24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "does_not_start_next_ability": True,
        "does_not_add_another_parser_rule": True,
        "headline": {
            "quality_reference": body.get("quality_reference"),
            "summary": body.get("summary"),
        },
    }


def write_leftover_29(payload: dict[str, object] | None = None, path: Path | None = None) -> Path:
    target = path or LEFTOVER_29_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    body = payload or run_leftover_29()
    target.write_text(
        json.dumps(freeze_leftover_29(body), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
