"""Diagnosis: user questions versus retrieval gold. Does not change gold."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.retrieval.conclusions import load_tabular_probability_baseline
from overgraph_ingest.tabular.gold import QUESTION_IDS, SELECTED_DOCUMENTS, USER_QUESTIONS, load_tabular_golds

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
GOLD_DIR = ROOT / "retrieval_gold"
QUESTION_GOLD_ID = "phase2-tabular-question-gold-v1"
QUESTION_GOLD_PATH = ROOT / "baselines" / f"{QUESTION_GOLD_ID}.json"

FALSE_ANSWER_LABELS = {
    ("Avtal_07_Sekretessavtal_omsesidigt", "confidentiality"): (
        "gold_omission",
        "Operative NDA duty. Matches gold notes. Missing from relevant_units.",
    ),
    ("Avtal_30_Ramavtal_tjanster", "confidentiality"): (
        "gold_omission",
        "Operative secrecy duty. Matches gold notes. Missing from relevant_units.",
    ),
    ("Avtal_13_Avgangsvederlagsavtal", "confidentiality"): (
        "nearby_relation",
        "Cited 6.3 (avtalets innehåll) instead of gold 6.1 (tystnadsplikt).",
    ),
    ("Avtal_05_Konsultavtal", "confidentiality"): (
        "nearby_relation",
        "Gold-positive document, cited the liability cap.",
    ),
    ("Avtal_36_Underleverantorsavtal", "confidentiality"): (
        "nearby_relation",
        "Gold-positive document, cited the liability cap.",
    ),
    ("Avtal_09_Kundbearbetningsforbud_varvningsforbud", "liability-cap"): (
        "nearby_relation",
        "Vite is a sanction, not a cap. Gold and a careful reading of the user question agree.",
    ),
    ("Avtal_25_Fastighetsservice_stadning", "notice-period"): (
        "gold_narrower",
        "Notice to stop auto-renewal. User question asks which notice applies. Gold wants a standing terminate-the-agreement term.",
    ),
    ("Avtal_30_Ramavtal_tjanster", "notice-period"): (
        "gold_narrower",
        "Same: notice attached to auto-renewal, not listed as standing notice.",
    ),
    ("Avtal_04_Timanstallning_behovsanstallning", "notice-period"): (
        "gold_narrower",
        "Immediate termination answers 'vilken uppsägningstid'. Gold wants a standing period.",
    ),
    ("Avtal_03_Visstidsanstallning", "notice-period"): (
        "gold_narrower",
        "Optional bracketed early-termination notice. Gold notes exclude that.",
    ),
    ("Avtal_02_Provanstallningsavtal", "notice-period"): (
        "gold_narrower",
        "Notice after conversion to permanent employment. Not in gold.",
    ),
    ("Avtal_02_Provanstallningsavtal", "auto-renewal"): (
        "gold_narrower",
        "Probation converts automatically. User question can read that as yes. Gold wants commercial tacit renewal.",
    ),
    ("Avtal_11_Distansarbetsavtal", "auto-renewal"): (
        "gold_narrower",
        "Gäller tills vidare from day one. Gold notes exclude that. User question does not.",
    ),
    ("Avtal_03_Visstidsanstallning", "auto-renewal"): (
        "product_polarity",
        "ANSWERED with a clause that the employment ends. That is a no, not a yes.",
    ),
    ("Avtal_36_Underleverantorsavtal", "auto-renewal"): (
        "nearby_relation",
        "Duration until the assignment is finished is not automatic period renewal.",
    ),
    ("Avtal_25_Fastighetsservice_stadning", "confidentiality"): (
        "nearby_relation",
        "Staff may not look at papers. Not an operative NDA duty.",
    ),
    ("Avtal_08_Konkurrensforbudsavtal", "confidentiality"): (
        "nearby_relation",
        "Says this agreement does not affect an existing duty. Pointer, not the duty.",
    ),
}


def review_question_gold(
    *,
    gold_dir: Path | None = None,
    probability: dict[str, object] | None = None,
    write_table: bool = True,
) -> dict[str, object]:
    golds = {gold.id: gold for gold in load_tabular_golds(gold_dir or GOLD_DIR)}
    wordings = []
    for question_id in QUESTION_IDS:
        gold = golds[question_id]
        selected = [
            path for path in SELECTED_DOCUMENTS if path in set(gold.relevant_documents)
        ]
        wordings.append(
            {
                "question_id": question_id,
                "user_question": USER_QUESTIONS[question_id],
                "gold_query": gold.query,
                "classify_question": gold.classify_question,
                "gold_notes": gold.notes,
                "gold_positive_in_selection": selected,
                "user_equals_gold_query": USER_QUESTIONS[question_id] == gold.query,
                "user_equals_classify": USER_QUESTIONS[question_id] == gold.classify_question,
            }
        )
    rows = list((probability or load_tabular_probability_baseline()).get("observations") or [])
    false_rows = [row for row in rows if row.get("outcome") == "false_answer"]
    labeled = []
    for row in false_rows:
        key = (str(row["document_id"]), str(row["question_id"]))
        kind, reason = FALSE_ANSWER_LABELS[key]
        labeled.append(
            {
                "document_id": key[0],
                "question_id": key[1],
                "gold_positive": bool(row.get("gold_positive")),
                "citation_relevant": bool(row.get("citation_relevant")),
                "kind": kind,
                "reason": reason,
            }
        )
    counts = _count(labeled)
    payload = {
        "operation": "tabular_question_gold",
        "experiment": QUESTION_GOLD_ID,
        "does_not_change_gold": True,
        "does_not_change_user_questions": True,
        "does_not_change_default_prompt": True,
        "do_not_retune_gold_to_model": True,
        "historical_cell_accuracy_is_not_user_quality": True,
        "user_question_is_the_contract": True,
        "wordings": wordings,
        "internal_gold_tension": {
            "question_id": "auto-renewal",
            "notes_exclude": "tills vidare",
            "gold_includes": "Avtal_18_Hyresavtal_bostad.docx: Annars förlängs avtalet tills vidare.",
        },
        "p1_false_answered": len(false_rows),
        "labeled": labeled,
        "counts": counts,
        "best_aligned": "liability-secrecy-carveout",
        "headline": {
            "three_wordings_are_not_the_same_task": True,
            "gold_negative_false_answers": sum(
                1 for row in labeled if not row["gold_positive"]
            ),
            "wrong_citation_on_gold_positive": sum(
                1 for row in labeled if row["gold_positive"]
            ),
            "counts": counts,
            "next_is_not_parameter_tuning": True,
        },
    }
    if write_table:
        write_question_gold_table(payload)
    return payload


def freeze_question_gold(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": QUESTION_GOLD_ID,
        "label": (
            "Frozen diagnosis: tabular user questions are not the same task "
            "as retrieval/classify gold. Historical 78% is agreement with "
            "passage gold, not user-question quality. Retrieval gold is "
            "unchanged. Default P0 stays."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_change_gold": True,
        "do_not_retune_gold_to_model": True,
        "historical_cell_accuracy_is_not_user_quality": True,
        "user_question_is_the_contract": True,
        "headline": payload.get("headline"),
        "wordings": payload.get("wordings"),
        "labeled": payload.get("labeled"),
        "counts": payload.get("counts"),
        "internal_gold_tension": payload.get("internal_gold_tension"),
    }


def write_question_gold_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or QUESTION_GOLD_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_question_gold(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_question_gold_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "question-gold-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# User questions versus gold",
        "",
        "Gold, user questions, and P0 are unchanged.",
        "This is not a retune of gold after model answers.",
        "Historical 78% cell accuracy is agreement with passage gold,",
        "not user-question quality.",
        "",
        "## Three wordings, three tasks",
        "",
        "Jev sees the user question. Gold was written for retrieval",
        "inventory and classify. Tabular scores cells against passage gold.",
        "",
        "| Fråga | Användarfråga (Jev) | Gold-query | Classify | Gold+ i urvalet |",
        "|---|---|---|---|---:|",
    ]
    for row in payload["wordings"]:
        lines.append(
            "| {question_id} | {user_question} | {gold_query} | {classify_question} | {n} |".format(
                n=len(row["gold_positive_in_selection"]),
                **row,
            )
        )
    tension = payload["internal_gold_tension"]
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "Liability-cap gold includes a monetary cap *or* an exclusion of",
            "indirect loss. The user question only asks whether liability is",
            "limited. Vite, settlement, insurance, and statutory allocation",
            "are left to the notes.",
            "",
            "Auto-renewal notes exclude `tills vidare`, but Avtal 18 gold is",
            f"`{tension['gold_includes']}`.",
            "",
            "## P1 false ANSWERED are mostly gold-negative",
            "",
            f"Of {payload['p1_false_answered']} false `ANSWERED` on the probability run:",
            "",
            f"- Gold-negative (model answered, gold has no unit): "
            f"{payload['headline']['gold_negative_false_answers']}",
            f"- Gold-positive, wrong citation: "
            f"{payload['headline']['wrong_citation_on_gold_positive']}",
            "",
            "| Kind | n |",
            "|---|---:|",
            f"| gold_omission | {counts.get('gold_omission', 0)} |",
            f"| gold_narrower | {counts.get('gold_narrower', 0)} |",
            f"| nearby_relation | {counts.get('nearby_relation', 0)} |",
            f"| product_polarity | {counts.get('product_polarity', 0)} |",
            "",
            "## What this is not",
            "",
            "- Not a reason to change gold so the model scores higher.",
            "- Not a reason to connect D's named exclusions.",
            "- Not a new prompt, controller, or score threshold.",
            "",
            "Carve-out is the best-aligned question: user, classify, and",
            "gold notes ask for the same relation. It was also the only",
            "question with zero false `ANSWERED` on P1.",
            "",
            "The user question is the contract for Socialism Tabular Review.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _count(rows: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        kind = str(row["kind"])
        counts[kind] = counts.get(kind, 0) + 1
    return counts
