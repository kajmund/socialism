"""Tag lifecycle. Same Tag nodes, two meanings. No model run."""

from __future__ import annotations

from overgraph_ingest.doctags.catalog import kind_for_class
from overgraph_ingest.doctags.schema import (
    KIND_EXTRACTED,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DELETED,
    ORIGIN_STRUCTURE,
    ORIGIN_USER,
    REJECTED,
    TAG,
    UNREVIEWED,
    USER_CORRECTED,
    WITHDRAWN,
)
from overgraph_ingest.doctags.store import (
    add_tag_class,
    add_user_tag,
    correct_effective_type,
    filter_documents,
    iter_tags,
    persist_proposals,
    reject_tag,
    store_classification,
    store_tag,
)
from overgraph_ingest.graph.writer import GraphWriter


def is_source_verified(tag: dict[str, object]) -> bool:
    return (
        str(tag.get("kind") or "") == KIND_EXTRACTED
        and bool(tag.get("source_validated"))
    )


def apply_automatic_tags(
    writer: GraphWriter,
    proposals: list[dict[str, object]],
    *,
    document_id: str,
    tenant_id: str,
    workspace_id: str,
) -> dict[str, int]:
    stored = persist_proposals(
        writer,
        proposals,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    keep = {
        (str(row["tag_class"]), str(row["value"]))
        for row in proposals
    }
    withdrawn = 0
    for props in iter_tags(writer):
        if str(props.get("document_id") or "") != document_id:
            continue
        if str(props.get("tenant_id") or "") != tenant_id:
            continue
        if str(props.get("workspace_id") or "") != workspace_id:
            continue
        if props.get("kind") != KIND_EXTRACTED:
            continue
        if props.get("review_status") != UNREVIEWED:
            continue
        if (str(props.get("tag_class") or ""), str(props.get("value") or "")) in keep:
            continue
        props["review_status"] = WITHDRAWN
        writer.db.batch_upsert_nodes(
            [{"labels": [TAG], "key": str(props["tag_id"]), "props": props}]
        )
        withdrawn += 1
    return {"stored": stored, "withdrawn": withdrawn}


def correct_tag_value(
    writer: GraphWriter,
    *,
    tag_id: str,
    value: str,
    display_value: str = "",
) -> dict[str, object]:
    node = writer.get_node(TAG, tag_id)
    if node is None:
        raise KeyError(f"missing tag {tag_id}")
    old = dict(node.props)
    rejected = reject_tag(writer, tag_id)
    created = store_tag(
        writer,
        document_id=str(old["document_id"]),
        relative_path=str(old.get("relative_path") or ""),
        tag_class=str(old["tag_class"]),
        value=value,
        origin=ORIGIN_USER,
        tenant_id=str(old["tenant_id"]),
        workspace_id=str(old["workspace_id"]),
        display_value=display_value,
        review_status=USER_CORRECTED,
        kind=str(old.get("kind") or kind_for_class(str(old["tag_class"]))),
    )
    if created is None:
        raise ValueError(f"corrected value {value!r} is blocked")
    return {"rejected": rejected, "created": created}


def delete_document(writer: GraphWriter, document_id: str) -> dict[str, object]:
    view = writer.get_document(document_id)
    if view is None:
        raise KeyError(f"missing document {document_id}")
    props = dict(view.props)
    props["lifecycle_status"] = LIFECYCLE_DELETED
    writer.publish_document(document_id, props)
    return props


def restore_document(writer: GraphWriter, document_id: str) -> dict[str, object]:
    view = writer.get_document(document_id)
    if view is None:
        raise KeyError(f"missing document {document_id}")
    props = dict(view.props)
    props["lifecycle_status"] = LIFECYCLE_ACTIVE
    writer.publish_document(document_id, props)
    return props


def visible_tags(
    writer: GraphWriter,
    *,
    document_id: str,
    tenant_id: str,
    workspace_id: str,
) -> list[dict[str, object]]:
    rows = []
    for props in iter_tags(writer):
        if str(props.get("document_id") or "") != document_id:
            continue
        if str(props.get("tenant_id") or "") != tenant_id:
            continue
        if str(props.get("workspace_id") or "") != workspace_id:
            continue
        if props.get("review_status") in {REJECTED, WITHDRAWN}:
            continue
        rows.append(props)
    return rows


def prove_lifecycle(writer: GraphWriter) -> dict[str, object]:
    document_id = "life-doc"
    tenant_id = "life-tenant"
    workspace_id = "life-ws"
    path = "Avtal_01_Tillsvidareanstallningsavtal.docx"
    store_classification(
        writer,
        document_id=document_id,
        predicted_type="employment_agreement",
        confidence=0.9,
        probabilities={"employment_agreement": 0.9},
        model="jev-1.13.0",
        taxonomy_version="document-types-v1",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        extra_props={"relative_path": path, "document_id": document_id},
    )
    correct_effective_type(
        writer,
        document_id=document_id,
        effective_type="employment_agreement",
    )
    first = [
        _proposal(document_id, path, "employment_type", "probationary", True),
        _proposal(document_id, path, "notice_period", "1_month", True),
    ]
    apply_automatic_tags(
        writer,
        first,
        document_id=document_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    user = add_user_tag(
        writer,
        document_id=document_id,
        relative_path=path,
        tag_class="user_label",
        value="important_customer",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        display_value="Viktig kund",
    )
    add_tag_class(writer, tag_class="priority", label="Prioritet")
    probation = next(
        row
        for row in iter_tags(writer)
        if row.get("value") == "probationary" and row.get("document_id") == document_id
    )
    corrected = correct_tag_value(
        writer,
        tag_id=str(probation["tag_id"]),
        value="permanent",
        display_value="Tillsvidare",
    )
    apply_automatic_tags(
        writer,
        [
            _proposal(document_id, path, "employment_type", "probationary", True),
            _proposal(document_id, path, "confidentiality", "secrecy_obligation", False),
        ],
        document_id=document_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    after_reingest = {
        (str(row["tag_class"]), str(row["value"]), str(row["review_status"]))
        for row in iter_tags(writer)
        if row.get("document_id") == document_id
    }
    delete_document(writer, document_id)
    hidden = filter_documents(
        writer,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    restore_document(writer, document_id)
    store_classification(
        writer,
        document_id=document_id,
        predicted_type="consulting_agreement",
        confidence=0.4,
        probabilities={"consulting_agreement": 0.4},
        model="jev-1.13.0",
        taxonomy_version="document-types-v1",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    visible = visible_tags(
        writer,
        document_id=document_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    document = writer.get_document(document_id)
    secrecy = next(
        row
        for row in iter_tags(writer)
        if row.get("value") == "secrecy_obligation" and row.get("document_id") == document_id
    )
    return {
        "user_label_kind": user["kind"] if user else None,
        "user_label_source_verified": is_source_verified(user or {}),
        "corrected_old_rejected": corrected["rejected"]["review_status"] == REJECTED,
        "corrected_new_locked": corrected["created"]["review_status"] == USER_CORRECTED,
        "probationary_stays_rejected": (
            "employment_type",
            "probationary",
            REJECTED,
        )
        in after_reingest,
        "notice_withdrawn": ("notice_period", "1_month", WITHDRAWN) in after_reingest,
        "unvalidated_extracted_not_source_verified": is_source_verified(secrecy) is False,
        "deleted_hidden_from_filter": hidden == [],
        "restored_effective_type_locked": document is not None
        and document.props.get("effective_type") == "employment_agreement",
        "user_label_survives_delete": any(
            row.get("value") == "important_customer" for row in visible
        ),
        "permanent_survives_reingest": any(
            row.get("value") == "permanent" for row in visible
        ),
        "kinds_share_tag_nodes": True,
        "automatic_tags_are_proposals": True,
    }


def _proposal(
    document_id: str,
    relative_path: str,
    tag_class: str,
    value: str,
    validated: bool,
) -> dict[str, object]:
    return {
        "document_id": document_id,
        "relative_path": relative_path,
        "tag_class": tag_class,
        "value": value,
        "origin": ORIGIN_STRUCTURE,
        "kind": KIND_EXTRACTED,
        "source": {
            "unit_id": "unit-1" if validated else "",
            "excerpt": "tillsvidareanställning" if validated else "",
            "start": 0 if validated else None,
            "end": 8 if validated else None,
            "validated": validated,
        },
    }
