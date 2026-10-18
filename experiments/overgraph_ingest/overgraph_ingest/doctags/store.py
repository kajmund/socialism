"""Store classification and tags on OverGraph Document/Tag nodes."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from overgraph_ingest.doctags.catalog import (
    CATALOG_VERSION,
    USER_LABEL,
    display_for,
    kind_for_class,
)
from overgraph_ingest.doctags.schema import (
    HAS_TAG,
    HIDDEN_REVIEW,
    KIND_USER_LABEL,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DELETED,
    LOCKED_REVIEW,
    ORIGIN_JEV,
    ORIGIN_USER,
    REJECTED,
    TAG,
    TAG_CLASS,
    TYPE_ORIGIN_MODEL,
    TYPE_ORIGIN_USER,
    UNREVIEWED,
    USER_CORRECTED,
    USER_VERIFIED,
)
from overgraph_ingest.doctype.store import text_unit_snapshot
from overgraph_ingest.graph.schema import DOCUMENT
from overgraph_ingest.graph.writer import GraphWriter, open_database

def store_classification(
    writer: GraphWriter,
    *,
    document_id: str,
    predicted_type: str,
    confidence: float | None,
    probabilities: dict[str, object] | None,
    model: str,
    taxonomy_version: str,
    tenant_id: str,
    workspace_id: str,
    extra_props: dict[str, object] | None = None,
    classified_at: str | None = None,
) -> dict[str, object]:
    view = writer.get_document(document_id)
    props = dict(view.props) if view is not None else {}
    if extra_props:
        props.update(extra_props)
    locked = bool(props.get("type_locked")) or props.get("type_origin") == TYPE_ORIGIN_USER
    props["predicted_type"] = predicted_type
    props["classification_confidence"] = confidence
    props["classification_probabilities"] = json.dumps(probabilities or {}, ensure_ascii=False)
    props["classification_model"] = model
    props["taxonomy_version"] = taxonomy_version
    props["classified_at"] = classified_at or datetime.now(timezone.utc).isoformat()
    props["tenant_id"] = tenant_id
    props["workspace_id"] = workspace_id
    props["lifecycle_status"] = LIFECYCLE_ACTIVE
    if not locked:
        props["effective_type"] = predicted_type
        props["type_origin"] = TYPE_ORIGIN_MODEL
        props["type_locked"] = False
        props["review_status"] = UNREVIEWED
    writer.publish_document(document_id, props)
    return props


def correct_effective_type(
    writer: GraphWriter,
    *,
    document_id: str,
    effective_type: str,
) -> dict[str, object]:
    view = writer.get_document(document_id)
    if view is None:
        raise KeyError(f"missing document {document_id}")
    props = dict(view.props)
    props["effective_type"] = effective_type
    props["type_origin"] = TYPE_ORIGIN_USER
    props["type_locked"] = True
    props["review_status"] = USER_CORRECTED
    writer.publish_document(document_id, props)
    return props


def store_tag(
    writer: GraphWriter,
    *,
    document_id: str,
    relative_path: str,
    tag_class: str,
    value: str,
    origin: str,
    tenant_id: str,
    workspace_id: str,
    display_value: str = "",
    confidence: float | None = None,
    probabilities: dict[str, object] | None = None,
    review_status: str = UNREVIEWED,
    source: dict[str, object] | None = None,
    model: str = "",
    kind: str | None = None,
) -> dict[str, object] | None:
    if _blocked(writer, document_id, tag_class, value, tenant_id, workspace_id):
        return None
    tag_id = _tag_key(tenant_id, workspace_id, document_id, tag_class, value)
    source = source or {}
    resolved_kind = kind or kind_for_class(tag_class)
    props = {
        "tag_id": tag_id,
        "document_id": document_id,
        "relative_path": relative_path,
        "tag_class": tag_class,
        "value": value,
        "display_value": display_for(tag_class, value, display_value),
        "origin": origin,
        "kind": resolved_kind,
        "confidence": confidence,
        "probabilities": json.dumps(probabilities or {}, ensure_ascii=False),
        "review_status": review_status,
        "source_unit_id": source.get("unit_id") or "",
        "source_excerpt": source.get("excerpt") or "",
        "source_start": source.get("start"),
        "source_end": source.get("end"),
        "source_validated": bool(source.get("validated")),
        "model": model,
        "catalog_version": CATALOG_VERSION,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
    }
    writer.db.batch_upsert_nodes([{"labels": [TAG], "key": tag_id, "props": props}])
    _link(writer, document_id, tag_id)
    writer.db.batch_upsert_nodes(
        [
            {
                "labels": [TAG_CLASS],
                "key": tag_class,
                "props": {"tag_class": tag_class, "kind": resolved_kind},
            }
        ]
    )
    return props


def add_tag_class(
    writer: GraphWriter,
    *,
    tag_class: str,
    label: str,
    origin: str = ORIGIN_USER,
) -> dict[str, object]:
    props = {
        "tag_class": tag_class,
        "label": label,
        "origin": origin,
        "kind": KIND_USER_LABEL if origin == ORIGIN_USER else kind_for_class(tag_class),
    }
    writer.db.batch_upsert_nodes(
        [{"labels": [TAG_CLASS], "key": tag_class, "props": props}]
    )
    return props


def add_user_tag(
    writer: GraphWriter,
    *,
    document_id: str,
    relative_path: str,
    tag_class: str,
    value: str,
    tenant_id: str,
    workspace_id: str,
    display_value: str = "",
) -> dict[str, object] | None:
    return store_tag(
        writer,
        document_id=document_id,
        relative_path=relative_path,
        tag_class=tag_class,
        value=value,
        origin=ORIGIN_USER,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        display_value=display_value,
        review_status=USER_VERIFIED,
        kind=kind_for_class(tag_class),
    )


def set_tag_review(
    writer: GraphWriter,
    *,
    tag_id: str,
    review_status: str,
    value: str | None = None,
    display_value: str | None = None,
) -> dict[str, object]:
    node = writer.get_node(TAG, tag_id)
    if node is None:
        raise KeyError(f"missing tag {tag_id}")
    props = dict(node.props)
    props["review_status"] = review_status
    if value is not None:
        props["value"] = value
        props["origin"] = ORIGIN_USER
    if display_value is not None:
        props["display_value"] = display_value
    writer.db.batch_upsert_nodes([{"labels": [TAG], "key": tag_id, "props": props}])
    return props


def reject_tag(writer: GraphWriter, tag_id: str) -> dict[str, object]:
    return set_tag_review(writer, tag_id=tag_id, review_status=REJECTED)


def approve_tag(writer: GraphWriter, tag_id: str) -> dict[str, object]:
    return set_tag_review(writer, tag_id=tag_id, review_status=USER_VERIFIED)


def remove_tag(writer: GraphWriter, tag_id: str) -> dict[str, object]:
    return reject_tag(writer, tag_id)


def iter_tags(writer: GraphWriter) -> list[dict[str, Any]]:
    return [dict(node.props) | {"key": str(node.key)} for node in writer.iter_nodes(TAG)]


def filter_documents(
    writer: GraphWriter,
    *,
    tenant_id: str,
    workspace_id: str,
    effective_type: str | None = None,
    tag_class: str | None = None,
    tag_value: str | None = None,
) -> list[str]:
    allowed = {
        str(node.props.get("document_id") or node.key)
        for node in writer.iter_nodes(DOCUMENT)
        if str(node.props.get("tenant_id") or "") == tenant_id
        and str(node.props.get("workspace_id") or "") == workspace_id
        and str(node.props.get("lifecycle_status") or LIFECYCLE_ACTIVE) != LIFECYCLE_DELETED
        and (effective_type is None or str(node.props.get("effective_type") or "") == effective_type)
    }
    if tag_class is None and tag_value is None:
        return sorted(_paths(writer, allowed))
    tagged = set()
    for props in iter_tags(writer):
        if str(props.get("tenant_id") or "") != tenant_id:
            continue
        if str(props.get("workspace_id") or "") != workspace_id:
            continue
        if props.get("review_status") in HIDDEN_REVIEW:
            continue
        if tag_class is not None and props.get("tag_class") != tag_class:
            continue
        if tag_value is not None and props.get("value") != tag_value:
            continue
        tagged.add(str(props.get("document_id") or ""))
    return sorted(_paths(writer, allowed & tagged))


def _paths(writer: GraphWriter, document_ids: set[str]) -> list[str]:
    paths = []
    for node in writer.iter_nodes(DOCUMENT):
        document_id = str(node.props.get("document_id") or node.key)
        if document_id in document_ids:
            paths.append(str(node.props.get("relative_path") or node.key))
    return paths


def _tag_key(
    tenant_id: str,
    workspace_id: str,
    document_id: str,
    tag_class: str,
    value: str,
) -> str:
    return f"tag:{tenant_id}:{workspace_id}:{document_id}:{tag_class}:{value}"


def _blocked(
    writer: GraphWriter,
    document_id: str,
    tag_class: str,
    value: str,
    tenant_id: str,
    workspace_id: str,
) -> bool:
    for props in iter_tags(writer):
        if (
            props.get("document_id") == document_id
            and props.get("tag_class") == tag_class
            and props.get("value") == value
            and props.get("tenant_id") == tenant_id
            and props.get("workspace_id") == workspace_id
            and props.get("review_status") in LOCKED_REVIEW
        ):
            return True
    return False


def _link(writer: GraphWriter, document_id: str, tag_id: str) -> None:
    document = writer.get_document(document_id)
    tag = writer.get_node(TAG, tag_id)
    if document is None or tag is None:
        return
    writer.db.batch_upsert_edges(
        [{"from_id": int(document.id), "to_id": int(tag.id), "label": HAS_TAG}]
    )


DEFAULT_TENANT = "experiment"
DEFAULT_WORKSPACE = "phase2-tags"


def persist_proposals(
    writer: GraphWriter,
    proposals: list[dict[str, object]],
    *,
    tenant_id: str = DEFAULT_TENANT,
    workspace_id: str = DEFAULT_WORKSPACE,
) -> int:
    stored = 0
    for row in proposals:
        result = store_tag(
            writer,
            document_id=str(row["document_id"]),
            relative_path=str(row["relative_path"]),
            tag_class=str(row["tag_class"]),
            value=str(row["value"]),
            origin=str(row.get("origin") or ORIGIN_JEV),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            display_value=str(row.get("display_value") or ""),
            confidence=row.get("confidence") if isinstance(row.get("confidence"), (int, float)) else None,
            probabilities=row.get("probabilities") if isinstance(row.get("probabilities"), dict) else None,
            source=dict(row.get("source") or {}),
            model=str(row.get("model") or ""),
            kind=str(row["kind"]) if row.get("kind") else None,
        )
        if result is not None:
            stored += 1
    return stored


def prove_store_filter_corrections(
    classifications: list[dict[str, object]],
    proposals: list[dict[str, object]],
    *,
    db_path: Path,
    dense_dimension: int = 8,
    tenant_id: str = DEFAULT_TENANT,
    workspace_id: str = DEFAULT_WORKSPACE,
) -> dict[str, object]:
    db = open_database(db_path, dense_dimension)
    try:
        writer = GraphWriter(db, batch_size=50)
        before_units = text_unit_snapshot(writer)
        write_started = time.perf_counter()
        for row in classifications:
            store_classification(
                writer,
                document_id=str(row["document_id"]),
                predicted_type=str(row["predicted_type"]),
                confidence=row.get("confidence") if isinstance(row.get("confidence"), (int, float)) else None,
                probabilities=row.get("probabilities") if isinstance(row.get("probabilities"), dict) else None,
                model=str(row.get("model") or ""),
                taxonomy_version=str(row.get("taxonomy_version") or ""),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                extra_props={
                    "relative_path": row["relative_path"],
                    "document_id": row["document_id"],
                },
            )
        persist_proposals(writer, proposals, tenant_id=tenant_id, workspace_id=workspace_id)
        write_seconds = time.perf_counter() - write_started
        db.flush()
        after_units = text_unit_snapshot(writer)
        first = classifications[0]
        document_id = str(first["document_id"])
        predicted = str(first["predicted_type"])
        corrected = "other" if predicted != "other" else "employment_agreement"
        correct_effective_type(writer, document_id=document_id, effective_type=corrected)
        store_classification(
            writer,
            document_id=document_id,
            predicted_type=predicted,
            confidence=first.get("confidence") if isinstance(first.get("confidence"), (int, float)) else None,
            probabilities=first.get("probabilities") if isinstance(first.get("probabilities"), dict) else None,
            model=str(first.get("model") or ""),
            taxonomy_version=str(first.get("taxonomy_version") or ""),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        locked = writer.get_document(document_id)
        type_survived = (
            locked is not None
            and locked.props.get("effective_type") == corrected
            and locked.props.get("predicted_type") == predicted
            and bool(locked.props.get("type_locked"))
        )
        rejected = None
        if proposals:
            first = next(
                (
                    row
                    for row in iter_tags(writer)
                    if row.get("relative_path") == proposals[0]["relative_path"]
                    and row.get("tag_class") == proposals[0]["tag_class"]
                    and row.get("value") == proposals[0]["value"]
                    and row.get("tenant_id") == tenant_id
                    and row.get("workspace_id") == workspace_id
                ),
                None,
            )
            if first is not None:
                rejected = reject_tag(writer, str(first["tag_id"]))
                persist_proposals(
                    writer,
                    proposals[:1],
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                )
        user_tag = add_user_tag(
            writer,
            document_id=document_id,
            relative_path=str(first["relative_path"]),
            tag_class=USER_LABEL,
            value="important_customer",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            display_value="Viktig kund",
        )
        add_tag_class(writer, tag_class="priority", label="Prioritet")
        store_classification(
            writer,
            document_id=f"{document_id}-other",
            predicted_type=predicted,
            confidence=None,
            probabilities=None,
            model="",
            taxonomy_version="",
            tenant_id="other-tenant",
            workspace_id="other-workspace",
            extra_props={
                "relative_path": "other.docx",
                "document_id": f"{document_id}-other",
            },
        )
        filter_started = time.perf_counter()
        by_type = filter_documents(
            writer,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            effective_type=corrected,
        )
        by_tag = filter_documents(
            writer,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            tag_class=USER_LABEL,
            tag_value="important_customer",
        )
        isolated = filter_documents(
            writer,
            tenant_id="other-tenant",
            workspace_id="other-workspace",
        )
        filter_seconds = time.perf_counter() - filter_started
        still_rejected = False
        if rejected is not None:
            node = writer.get_node(TAG, str(rejected["tag_id"]))
            still_rejected = node is not None and node.props.get("review_status") == REJECTED
        return {
            "documents": len(classifications),
            "tags": len(iter_tags(writer)),
            "text_units_before": len(before_units),
            "text_units_after": len(after_units),
            "text_units_unchanged": before_units == after_units,
            "write_seconds": write_seconds,
            "filter_seconds": filter_seconds,
            "type_correction_survives_reclassify": type_survived,
            "rejected_tag_stays_rejected": still_rejected,
            "user_tag_stored": user_tag is not None,
            "filter_by_corrected_type": by_type,
            "filter_by_user_tag": by_tag,
            "other_tenant_paths": isolated,
            "tenant_isolation": "other.docx" not in by_type and isolated == ["other.docx"],
        }
    finally:
        db.close()

