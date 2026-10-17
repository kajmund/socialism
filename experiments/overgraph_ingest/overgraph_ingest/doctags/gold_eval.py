"""Freeze tag gold. Models are not run."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.doctags.catalog import CATALOG_VERSION, TAG_CLASSES
from overgraph_ingest.doctags.gold import (
    DOCUMENTS,
    GOLD_ID,
    TAG_GOLDS,
    assert_tag_gold_complete,
    golds_for,
)

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
DOCUMENT_TAGS_GOLD_ID = "phase2-document-tags-gold-v1"
DOCUMENT_TAGS_GOLD_PATH = ROOT / "baselines" / f"{DOCUMENT_TAGS_GOLD_ID}.json"


def review_document_tags_gold() -> dict[str, object]:
    assert_tag_gold_complete()
    counts = {tag_class: 0 for tag_class in TAG_CLASSES}
    for item in TAG_GOLDS:
        counts[item.tag_class] += 1
    return {
        "operation": "document_tags_gold",
        "experiment": DOCUMENT_TAGS_GOLD_ID,
        "gold_id": GOLD_ID,
        "catalog_version": CATALOG_VERSION,
        "does_not_run_jev": True,
        "models_not_run": True,
        "does_not_change_text_units": True,
        "does_not_change_retrieval": True,
        "does_not_change_answer_cell": True,
        "does_not_change_default_hybrid": True,
        "does_not_change_doctype_baseline": True,
        "default_remains_d": True,
        "no_production_integration": True,
        "prepared_knowledge_not_legal_proof": True,
        "inventory": inventory_notes(),
        "documents": list(DOCUMENTS),
        "labels": [
            {
                "relative_path": item.relative_path,
                "tag_class": item.tag_class,
                "value": item.value,
                "display_value": item.display_value,
                "contains": item.contains,
            }
            for item in TAG_GOLDS
        ],
        "per_document": [
            {
                "relative_path": path,
                "tags": [
                    {
                        "tag_class": item.tag_class,
                        "value": item.value,
                        "display_value": item.display_value,
                    }
                    for item in golds_for(path)
                ],
            }
            for path in DOCUMENTS
        ],
        "headline": {
            "documents": len(DOCUMENTS),
            "tags": len(TAG_GOLDS),
            "counts": counts,
            "models_not_run": True,
        },
    }


def inventory_notes() -> dict[str, object]:
    return {
        "socialism_has_document_tag_model": False,
        "openapi_tags_are_unrelated": True,
        "speaker_user_label_is_unrelated": True,
        "passage_marks_are_highlights_not_tags": True,
        "expertgranskning_document_type_is_free_text": True,
        "reuse_experiment_overgraph": True,
        "reuse_frozen_doctype_b": True,
        "do_not_create_parallel_tag_database": True,
        "tenant_props": ("tenant_id", "workspace_id"),
        "jev_fields_stored_raw": ("confidence", "probabilities"),
        "citation_path": "TextUnit excerpt must be an exact substring",
    }


def freeze_document_tags_gold(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": DOCUMENT_TAGS_GOLD_ID,
        "label": (
            "Document-tag gold for 16 phase-2 contracts. "
            "Locked before tag-extraction Jev. Limited tag classes."
        ),
        "do_not_overwrite": True,
        "does_not_run_jev": True,
        "models_not_run": True,
        "does_not_change_text_units": True,
        "does_not_change_retrieval": True,
        "does_not_change_answer_cell": True,
        "does_not_change_doctype_baseline": True,
        "default_remains_d": True,
        "prepared_knowledge_not_legal_proof": True,
        "gold_id": payload.get("gold_id"),
        "catalog_version": payload.get("catalog_version"),
        "documents": payload.get("documents"),
        "headline": payload.get("headline"),
        "inventory": payload.get("inventory"),
        "labels": payload.get("labels"),
        "per_document": payload.get("per_document"),
    }


def write_document_tags_gold_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or DOCUMENT_TAGS_GOLD_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_document_tags_gold(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def write_document_tags_gold_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "document-tags-gold-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    counts = payload["headline"]["counts"]
    lines = [
        "# Document-tag gold",
        "",
        "Gold before models. Limited tag classes. Not legal proof.",
        "No Jev. No retrieval change. No `answer_cell` change.",
        "Frozen doctype baseline is unchanged.",
        "",
        "## Inventory",
        "",
        "Socialism has no document-tag model. OpenAPI tags, speaker",
        "`user_label`, passage marks, and expertgranskning `document_type`",
        "are unrelated. The experiment extends OverGraph in this package",
        "and reuses frozen document-type B. It does not create a second",
        "tag database.",
        "",
        "## Counts",
        "",
        "| Class | Tags |",
        "|---|---:|",
    ]
    for tag_class, count in counts.items():
        lines.append(f"| `{tag_class}` | {count} |")
    lines.extend(
        [
            "",
            f"Documents: {payload['headline']['documents']}.",
            f"Tags: {payload['headline']['tags']}.",
            "",
            "## What this is not",
            "",
            "- Not Tabular Review.",
            "- Not a new document type experiment.",
            "- Not production ingest.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_inventory_table(payload, directory)
    return target


def write_inventory_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "document-tags-inventory-v1.md"
    notes = payload["inventory"]
    lines = [
        "# Document tags inventory",
        "",
        "Completed before implementation.",
        "",
        "| Finding | Value |",
        "|---|---|",
    ]
    for key, value in notes.items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "Reuse experiment OverGraph Document/Tag nodes.",
            "Reuse frozen `phase2-doctype-run-v1` variant B for",
            "`predicted_type`, confidence, and probabilities.",
            "Do not import `backend/app`.",
            "",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def refuse_document_tags_run_before_gold() -> None:
    raise RuntimeError(
        "document-tag gold is not frozen yet. "
        "Do not call Jev before --document-tags-gold."
    )


def require_document_tags_gold(path: Path | None = None) -> Path:
    target = path or DOCUMENT_TAGS_GOLD_PATH
    if not target.is_file():
        refuse_document_tags_run_before_gold()
    return target
