"""User review history. Rejected answers are never reused as approved."""

from __future__ import annotations

from app.services.document_qa.access import QaPermissionError, Viewer
from app.services.document_qa.labels import ANSWER, HAS_REVIEW, REVIEW_EVENT
from app.services.document_qa.normalize import review_key
from app.services.document_qa.store import load_answer
from app.services.document_qa.types import LoadedAnswer
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.model import GraphRecord

_ACTIONS = {"approve": "user_verified", "reject": "rejected"}


def review_answer(
    catalog: Catalog,
    viewer: Viewer,
    answer_key: str,
    *,
    action: str,
    reviewed_at: str,
    reviewer: str,
) -> LoadedAnswer:
    status = _ACTIONS.get(action)
    if status is None:
        raise ValueError(f"unsupported review action: {action}")
    row = catalog.get_by_key(ANSWER, answer_key)
    if row is None:
        raise KeyError(answer_key)
    _require_answer_access(viewer, row)
    props = dict(row.props)
    props["review_status"] = status
    catalog.upsert_node(list(row.labels), row.key, props=props)
    _append_review(catalog, viewer, row, action=action, reviewed_at=reviewed_at, reviewer=reviewer)
    loaded = load_answer(catalog, answer_key)
    if loaded is None:
        raise RuntimeError("reviewed answer is missing after write")
    return loaded


def review_history(catalog: Catalog, answer_key: str) -> tuple[dict[str, str], ...]:
    row = catalog.get_by_key(ANSWER, answer_key)
    if row is None or row.engine_id is None:
        return ()
    events = []
    for engine_id in catalog.neighbors(row.engine_id, edge_label_filter=[HAS_REVIEW]):
        event = catalog.get(engine_id)
        if event is None or REVIEW_EVENT not in event.labels:
            continue
        events.append(
            {
                "action": str(event.props.get("action") or ""),
                "reviewed_at": str(event.props.get("reviewed_at") or ""),
                "reviewer": str(event.props.get("reviewer") or ""),
            }
        )
    return tuple(sorted(events, key=lambda item: item["reviewed_at"]))


def _require_answer_access(viewer: Viewer, row: GraphRecord) -> None:
    document_id = str(row.props.get("document_id") or "")
    version_id = str(row.props.get("document_version_id") or "")
    if not viewer.can_read(document_id, version_id):
        raise QaPermissionError("workspace or document is not readable")


def _append_review(
    catalog: Catalog,
    viewer: Viewer,
    answer: GraphRecord,
    *,
    action: str,
    reviewed_at: str,
    reviewer: str,
) -> None:
    key = review_key(viewer.customer_id, answer.key, reviewed_at, action)
    catalog.upsert_node(
        [REVIEW_EVENT],
        key,
        props={
            "answer_key": answer.key,
            "action": action,
            "reviewed_at": reviewed_at,
            "reviewer": reviewer,
        },
    )
    event = catalog.get_by_key(REVIEW_EVENT, key)
    if event is None or event.engine_id is None or answer.engine_id is None:
        raise RuntimeError("review event missing after upsert")
    catalog.upsert_edge(answer.engine_id, event.engine_id, HAS_REVIEW)
