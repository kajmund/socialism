"""Freeze the tag lifecycle review. Models are not run."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.doctags.lifecycle import prove_lifecycle
from overgraph_ingest.graph.writer import GraphWriter, open_database

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
LIFECYCLE_ID = "phase2-document-tags-lifecycle-v1"
LIFECYCLE_PATH = ROOT / "baselines" / f"{LIFECYCLE_ID}.json"


def review_document_tags_lifecycle() -> dict[str, object]:
    return {
        "operation": "document_tags_lifecycle",
        "experiment": LIFECYCLE_ID,
        "does_not_run_jev": True,
        "models_not_run": True,
        "does_not_change_text_units": True,
        "does_not_change_retrieval": True,
        "does_not_change_answer_cell": True,
        "does_not_change_doctype_baseline": True,
        "does_not_change_document_tags_run": True,
        "default_remains_d": True,
        "no_production_integration": True,
        "automatic_tags_are_proposals": True,
        "prepared_knowledge_not_legal_proof": True,
        "a_is_cheap_ingest_candidate": True,
        "b_is_experimental_semantic_alternative": True,
        "kinds": {
            "extracted_property": (
                "Automatic or user-reviewed document property. "
                "Source-verified only when the excerpt is validated."
            ),
            "user_label": (
                "Organizational label such as important or customer X. "
                "No document source is required."
            ),
        },
        "rules": [
            "Same Tag nodes. Kind distinguishes meaning.",
            "Identity is tenant, workspace, document, class, and value.",
            "Origin is an attribute, not the identity.",
            "User labels start verified and never require a source.",
            "Extracted tags stay proposals until a user reviews them.",
            "Rejected values stay rejected on re-ingest.",
            "Correcting a value rejects the old value and locks the new one.",
            "Unreviewed automatic tags not re-proposed are withdrawn.",
            "User decisions survive re-ingest, reclassify, and document delete.",
            "Delete hides the document from filters and keeps tag tombstones.",
            "Restore plus ingest of the same document id reapplies those decisions.",
            "Socialism must key decisions on a stable workspace document id.",
            "Automatic extraction should read effective_type, not predicted_type.",
        ],
        "gaps_closed": [
            "value_correction_did_not_block_old_value",
            "tag_identity_included_origin",
            "no_document_delete_path",
            "user_label_and_extracted_property_not_named",
            "stale_unreviewed_proposals_stayed_visible",
        ],
        "headline": {
            "models_not_run": True,
            "kinds": 2,
            "rules": 13,
        },
    }


def freeze_document_tags_lifecycle(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": LIFECYCLE_ID,
        "label": (
            "Document-tag lifecycle review. User labels versus extracted "
            "properties. No Jev. No new 16-document run."
        ),
        "do_not_overwrite": True,
        "does_not_run_jev": True,
        "models_not_run": True,
        "does_not_change_document_tags_run": True,
        "does_not_change_doctype_baseline": True,
        "does_not_change_answer_cell": True,
        "no_production_integration": True,
        "automatic_tags_are_proposals": True,
        "a_is_cheap_ingest_candidate": True,
        "b_is_experimental_semantic_alternative": True,
        "kinds": payload.get("kinds"),
        "rules": payload.get("rules"),
        "gaps_closed": payload.get("gaps_closed"),
        "proof": payload.get("proof"),
        "headline": payload.get("headline"),
    }


def write_document_tags_lifecycle_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or LIFECYCLE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_document_tags_lifecycle(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def write_document_tags_lifecycle_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "document-tags-lifecycle-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Document-tag lifecycle",
        "",
        "Design review after the 16-document tag run. No Jev.",
        "A stays the cheap ingest candidate. B stays an experimental",
        "alternative for more semantic classes. Automatic tags are",
        "proposals, not legal facts.",
        "",
        "## Two meanings, one Tag node",
        "",
        "| Kind | Meaning | Source |",
        "|---|---|---|",
        "| `extracted_property` | Typed document property | Required to present as source-verified |",
        "| `user_label` | Organizational label | Never required |",
        "",
        "## Rules",
        "",
    ]
    for rule in payload["rules"]:
        lines.append(f"- {rule}")
    proof = payload.get("proof") or {}
    if proof:
        lines.extend(["", "## Proof", "", "| Check | Value |", "|---|---|"])
        for key, value in proof.items():
            lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## What this is not",
            "",
            "- Not a new tag-quality experiment.",
            "- Not production ingest.",
            "- Not a change to Tabular `answer_cell`.",
            "- Not a new Jev prompt for harder legal properties.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def run_document_tags_lifecycle(*, db_path: Path | None = None) -> dict[str, object]:
    payload = review_document_tags_lifecycle()
    target = db_path or ROOT / "data" / "document-tags-lifecycle-v1"
    db = open_database(target, 8)
    try:
        payload["proof"] = prove_lifecycle(GraphWriter(db, batch_size=50))
    finally:
        db.close()
    proof = payload["proof"]
    payload["headline"]["proof_ok"] = (
        proof["user_label_kind"] == "user_label"
        and proof["user_label_source_verified"] is False
        and all(
            proof[key] is True
            for key in proof
            if key not in {"user_label_kind", "user_label_source_verified"}
        )
    )
    return payload
