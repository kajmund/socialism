"""Close the document-tag experiment. No Jev. No new 16-document run."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
CLOSE_ID = "phase2-document-tags-close-v1"
CLOSE_PATH = ROOT / "baselines" / f"{CLOSE_ID}.json"


def review_document_tags_close() -> dict[str, object]:
    return {
        "operation": "document_tags_close",
        "experiment": CLOSE_ID,
        "does_not_run_jev": True,
        "models_not_run": True,
        "does_not_change_document_tags_run": True,
        "does_not_change_document_tags_lifecycle": True,
        "does_not_change_doctype_baseline": True,
        "does_not_change_answer_cell": True,
        "does_not_import_backend": True,
        "no_production_integration": True,
        "experiment_closed": True,
        "do_not_run_more_jev_on_16_docs": True,
        "a_is_cheap_ingest_candidate": True,
        "b_is_experimental_semantic_alternative": True,
        "automatic_tags_are_proposals": True,
        "carry_to_socialism": {
            "document_catalog": (
                "Document type, tags, raw confidence/probabilities, "
                "and user corrections."
            ),
            "tabular_review": (
                "User questions answered from original text with citations."
            ),
            "product_loop": (
                "Filter which documents first, then ask what to know."
            ),
            "reuse_canonical_document": True,
            "reuse_document_version": True,
            "do_not_import_overgraph_ingest": True,
        },
        "identity": {
            "tag_identity_excludes_origin": True,
            "keep_proposer_and_reviewer_history": True,
            "logical_document_is_not_content_hash": True,
            "user_decisions_belong_to_canonical_document": True,
            "extracted_properties_and_sources_belong_to_document_version": True,
        },
        "deletion": {
            "archive_hides_and_keeps": True,
            "purge_removes_content_and_metadata": True,
            "experiment_delete_is_archive_only": True,
            "purge_not_solved_in_experiment": True,
        },
        "measured": {
            "doctype_b_accuracy": 0.86,
            "tag_a_recall": 0.9411764705882353,
            "tag_b_recall": 0.9411764705882353,
            "tag_filter_seconds": 0.002,
            "samples_are_separate_experiments": True,
        },
        "headline": {
            "experiment_closed": True,
            "models_not_run": True,
            "next": "plan_socialism_integration",
        },
    }


def freeze_document_tags_close(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": CLOSE_ID,
        "label": (
            "Closed document-tag experiment. Carry the data model into the "
            "Socialism integration plan. Do not run more Jev on the 16 documents."
        ),
        "do_not_overwrite": True,
        "does_not_run_jev": True,
        "models_not_run": True,
        "experiment_closed": True,
        "do_not_run_more_jev_on_16_docs": True,
        "does_not_change_document_tags_run": True,
        "does_not_change_answer_cell": True,
        "no_production_integration": True,
        "a_is_cheap_ingest_candidate": True,
        "b_is_experimental_semantic_alternative": True,
        "automatic_tags_are_proposals": True,
        "carry_to_socialism": payload.get("carry_to_socialism"),
        "identity": payload.get("identity"),
        "deletion": payload.get("deletion"),
        "measured": payload.get("measured"),
        "headline": payload.get("headline"),
    }


def write_document_tags_close_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or CLOSE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_document_tags_close(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def write_document_tags_close_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "document-tags-close-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Document-tag experiment closed",
        "",
        "No more Jev on the 16 documents. No new legal engine at ingest.",
        "Carry the data model into the Socialism integration plan.",
        "Do not import `overgraph_ingest` into `backend/app`.",
        "",
        "## Carry forward",
        "",
        "- Document catalog: type, tags, confidence, user corrections.",
        "- Tabular Review: questions with citations from original text.",
        "- Filter documents first, then ask what to know.",
        "- Reuse Socialism `CanonicalDocument` and `DocumentVersion`.",
        "",
        "## Identity",
        "",
        "- Tag identity excludes origin. Keep proposer and reviewer history.",
        "- User decisions belong on the logical document.",
        "- Extracted properties and sources belong on the document version.",
        "- Content hash is the version, not the document.",
        "",
        "## Deletion",
        "",
        "- Archive hides the document and keeps decisions.",
        "- Purge must remove content, tags, and excerpts.",
        "- Experiment delete is archive only. Purge is integration work.",
        "",
        "## What this is not",
        "",
        "- Not production ingest.",
        "- Not a change to Tabular `answer_cell`.",
        "- Not another quality run.",
        f"- Next: {payload['headline']['next']}.",
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
