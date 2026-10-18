"""Compact workspace state for an expert turn, and marks fetched only when asked."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceArtifact, WorkspaceReference
from app.observability.events import log_event
from app.schemas.workspace import WorkspaceState
from app.services.expert_reasoning import EVENT_DATASET_EXPERT_CHAT
from app.services.workspace.mark_author import marked_author
from app.services.workspace.passage_comments import list_passage_comments
from app.services.workspace.tool_arguments import ContextArguments
from app.services.workspace_document_context import (
    open_artifact_ids,
    relation_plain_text,
    voice_document_context,
)

SHORT_SELECTION_CHARS = 400
_RELATION_CHARS = 8000
_RECENT_TURNS = 4
_RECENT_CHARS = 240
logger = logging.getLogger(__name__)
_open_titles: ContextVar[dict[str, str] | None] = ContextVar("workspace_open_titles", default=None)


def bind_open_titles(documents: dict) -> None:
    """Titles are not stored on workspace state. The tool state rejects extra keys."""
    titles: dict[str, str] = {}
    for row in documents.get("open_documents") or []:
        _remember_title(titles, row.get("source_id"), row.get("filename"))
    for row in documents.get("created_documents") or []:
        _remember_title(titles, row.get("artifact_id"), row.get("title"))
    for row in documents.get("relation_maps") or []:
        _remember_title(titles, row.get("artifact_id"), row.get("title"))
    _open_titles.set(titles)


def turn_payload(
    state: WorkspaceState,
    documents: dict | None = None,
    *,
    text_mode: str = "short",
) -> dict[str, Any]:
    """Identity of what is on screen. Document text and saved marks stay out."""
    bundle = documents or {}
    return {
        "view": state.view,
        "knowledge_scope": state.knowledge_scope,
        "active_artifact_id": state.active_artifact_id,
        "active_source_id": state.active_source_id,
        "active_document_set_id": state.active_document_set_id,
        "documents": _open_tabs(state, bundle),
        "created_documents": _named(bundle.get("created_documents"), "artifact_id", "title"),
        "relation_maps": _named(bundle.get("relation_maps"), "artifact_id", "title"),
        "document_set": _document_set(bundle.get("shown_document_set")),
        "selection": compact_selection(state.selection, text_mode=text_mode),
        "document_mentions": [
            {"id": row.source_object_id, "title": row.display_name}
            for row in state.document_mentions
        ],
    }


def compact_selection(selection: Any, *, text_mode: str) -> dict[str, Any] | None:
    data = _as_dict(selection)
    if data is None:
        return None
    anchor = data.get("anchor") if isinstance(data.get("anchor"), dict) else {}
    exact = " ".join(str(anchor.get("exact_text") or data.get("text") or "").split())
    page = anchor.get("page_number")
    if not isinstance(page, int):
        page = data.get("page") if isinstance(data.get("page"), int) else None
    payload: dict[str, Any] = {
        "source_id": data.get("source_id"),
        "selection_id": data.get("selection_id") or data.get("reference_id"),
        "page": page,
        "has_text": bool(exact) or bool(data.get("has_text")),
    }
    if text_mode == "full" and exact:
        payload["text"] = exact[:12000]
    elif text_mode == "short" and exact and len(exact) <= SHORT_SELECTION_CHARS:
        payload["text"] = exact
    return payload


def routing_workspace(state: WorkspaceState | dict[str, Any] | None) -> dict[str, Any] | None:
    """What JEV may see. Passage text and file inventories are not included."""
    if state is None:
        return None
    payload = state.model_dump() if isinstance(state, WorkspaceState) else state
    if not isinstance(payload, dict):
        return None
    documents = []
    for row in payload.get("documents") or []:
        if not isinstance(row, dict):
            continue
        item: dict[str, Any] = {"source_id": row.get("source_id"), "page": row.get("page")}
        title = _title_for(row.get("source_id"), row.get("title") or row.get("filename"))
        if title:
            item["title"] = title
        documents.append(item)
    routed: dict[str, Any] = {
        "view": payload.get("view"),
        "active_source_id": payload.get("active_source_id"),
        "active_artifact_id": payload.get("active_artifact_id"),
        "documents": documents,
        "selection": compact_selection(payload.get("selection"), text_mode="none"),
        "document_mentions": [
            {"source_object_id": row.get("source_object_id")}
            for row in payload.get("document_mentions") or []
            if isinstance(row, dict) and row.get("source_object_id")
        ],
    }
    return routed


def with_recent_turns(
    state: WorkspaceState | dict[str, Any] | None,
    history: list,
) -> dict[str, Any] | None:
    lines = recent_lines(history)
    if state is None and not lines:
        return None
    if isinstance(state, WorkspaceState):
        payload = state.model_dump()
    elif isinstance(state, dict):
        payload = dict(state)
    else:
        payload = {}
    if lines:
        payload["recent_turns"] = lines
    return payload


def recent_lines(history: list) -> list[str]:
    lines = []
    for entry in history[-_RECENT_TURNS:]:
        text = " ".join(str(entry[1]).split())
        if text:
            lines.append(f"{entry[0]}: {text[:_RECENT_CHARS]}")
    return lines


def collect_passage_marks(references: list, state: WorkspaceState, user: UserAccount) -> list[dict]:
    """Named passages experts can attribute. Unnamed citations are not marks."""
    marks: list[dict] = []
    seen: set[tuple] = set()

    def add(
        kind: str, *, author_id: object, name: object, source_id: object, page: object,
        exact: object, reference_id: object,
    ) -> None:
        text = " ".join(str(exact or "").split())[:240]
        label = " ".join(str(name or "").split())
        if not text or not label or kind not in ("user", "expert") or not isinstance(author_id, str) or not author_id:
            return
        key = (kind, author_id, str(source_id or ""), page if isinstance(page, int) else None, text)
        if key in seen:
            return
        seen.add(key)
        marks.append({
            "kind": kind,
            "id": author_id,
            "name": label,
            "source_id": str(source_id or ""),
            "reference_id": reference_id if isinstance(reference_id, str) else None,
            "page": page if isinstance(page, int) else None,
            "exact_text": text,
        })

    for ref in references:
        author = marked_author(getattr(ref, "snapshot", None))
        anchor = getattr(ref, "anchor", None)
        anchor = anchor if isinstance(anchor, dict) else {}
        if author:
            snapshot = getattr(ref, "snapshot", None) or {}
            add(
                author["kind"],
                author_id=author["id"],
                name=author["name"],
                source_id=getattr(ref, "source_id", ""),
                page=anchor.get("page_number"),
                exact=anchor.get("exact_text") or snapshot.get("excerpt"),
                reference_id=getattr(ref, "id", None),
            )
    selection = state.selection
    anchor = selection.anchor if selection is not None else None
    if anchor is not None and anchor.exact_text and selection is not None:
        add(
            "user",
            author_id=user.id,
            name=_account_name(user),
            source_id=selection.source_id or "",
            page=anchor.page_number,
            exact=anchor.exact_text,
            reference_id=selection.reference_id,
        )
    return marks


def select_passage_marks(
    marks: list[dict],
    *,
    source_ids: list[str],
    expert_ids: list[str],
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    sources = set(source_ids)
    chosen = [
        mark for mark in marks
        if (not sources or mark.get("source_id") in sources) and _author_match(mark, expert_ids)
    ]
    return chosen[offset:offset + limit], len(chosen)


def log_dynamic_context(text: str) -> None:
    chars = len(text)
    log_event(
        logger,
        "expert_chat.context",
        dataset=EVENT_DATASET_EXPERT_CHAT,
        outcome="success",
        fields={
            "context": {
                "dynamic_context_chars": chars,
                "dynamic_context_tokens_estimate": chars // 4,
                "marks_in_prompt": 0,
            }
        },
    )


async def answered_workspace_context(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    user: UserAccount,
    *,
    turn_context: dict | None,
    arguments: dict,
) -> dict:
    """Live workspace identity. Marks and relation graphs only when the call asks."""
    args = ContextArguments.model_validate(arguments)
    live = WorkspaceState.model_validate(workspace.state)
    documents = await voice_document_context(session, workspace, user)
    payload = _workspace_payload(workspace, live, documents)
    if args.include_relations:
        payload["relations"] = await _open_relations(session, workspace, live)
    if args.source_ids or args.expert_ids:
        marks, comments, total = await _filtered_marks(
            session, workspace, user, live, args=args,
        )
        payload["passage_marks"] = marks
        payload["passage_comments"] = comments
        payload["passage_marks_total"] = total
        _log_marks(len(marks), total)
    return {"status": "completed", "workspace": payload, "turn_context": turn_context}


def _workspace_payload(workspace: VoiceWorkspace, live: WorkspaceState, documents: dict) -> dict:
    return {
        "id": workspace.id,
        "revision": workspace.revision,
        "title": workspace.title,
        "state": turn_payload(live, documents, text_mode="full"),
        "available_documents": list(documents.get("available_documents") or []),
        "open_documents": list(documents.get("open_documents") or []),
        "created_documents": _named(documents.get("created_documents"), "artifact_id", "title"),
        "relation_maps": _named(documents.get("relation_maps"), "artifact_id", "title"),
    }


async def _filtered_marks(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    user: UserAccount,
    live: WorkspaceState,
    *,
    args: ContextArguments,
) -> tuple[list[dict], list[dict], int]:
    references = list(await session.scalars(select(WorkspaceReference).where(
        WorkspaceReference.workspace_id == workspace.id,
    )))
    page, total = select_passage_marks(
        collect_passage_marks(references, live, user),
        source_ids=list(args.source_ids),
        expert_ids=list(args.expert_ids),
        limit=args.limit,
        offset=args.offset,
    )
    comments = [
        _comment(row)
        for row in await list_passage_comments(session, workspace)
        if _comment_match(row, list(args.source_ids), list(args.expert_ids))
    ]
    return page, comments[args.offset:args.offset + args.limit], total


async def _open_relations(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    live: WorkspaceState,
) -> list[dict]:
    open_ids = open_artifact_ids(live)
    rows = list(await session.scalars(select(WorkspaceArtifact).where(
        WorkspaceArtifact.workspace_id == workspace.id,
        WorkspaceArtifact.kind == "relations",
        WorkspaceArtifact.status == "ready",
    )))
    return [
        {
            "artifact_id": artifact.id,
            "title": artifact.title,
            "text": relation_plain_text(artifact.content)[:_RELATION_CHARS],
        }
        for artifact in rows
        if artifact.id in open_ids
    ]


def _comment(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "source_id": row.get("source_id"),
        "expert_id": row.get("expert_id"),
        "author_name": row.get("author_name"),
        "body": row.get("body"),
        "page": (row.get("anchor") or {}).get("page_number") if isinstance(row.get("anchor"), dict) else None,
    }


def _comment_match(row: dict, source_ids: list[str], expert_ids: list[str]) -> bool:
    if source_ids and row.get("source_id") not in source_ids:
        return False
    return _author_match(
        {"id": row.get("expert_id") or row.get("author_id"), "name": row.get("author_name")},
        expert_ids,
    )


def _author_match(mark: dict, expert_ids: list[str]) -> bool:
    if not expert_ids:
        return True
    author_id = str(mark.get("id") or "").casefold()
    name = str(mark.get("name") or "").casefold()
    for raw in expert_ids:
        token = " ".join(str(raw).casefold().split())
        if token and (token == author_id or token == name or name.startswith(f"{token} ")):
            return True
    return False


def _open_tabs(state: WorkspaceState, documents: dict) -> list[dict]:
    titles = {
        row.get("source_id"): row.get("filename")
        for row in documents.get("open_documents") or []
    }
    return [
        {"id": tab.source_id, "title": titles.get(tab.source_id), "page": tab.page}
        for tab in state.documents
    ]


def _named(rows: object, id_key: str, title_key: str) -> list[dict]:
    if not isinstance(rows, list):
        return []
    return [
        {"id": row.get(id_key), "title": row.get(title_key), "shown": bool(row.get("shown"))}
        for row in rows
        if isinstance(row, dict)
    ]


def _document_set(document_set: object) -> dict | None:
    if not isinstance(document_set, dict):
        return None
    documents = [
        {"id": row.get("source_id"), "title": row.get("filename")}
        for row in document_set.get("documents") or []
        if isinstance(row, dict)
    ]
    title = str(document_set.get("title") or "").strip()
    if not title or not documents:
        return None
    return {"title": title, "documents": documents}


def _as_dict(value: Any) -> dict | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value if isinstance(value, dict) else None


def _account_name(user: UserAccount) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or user.email


def _remember_title(titles: dict[str, str], key: object, title: object) -> None:
    if isinstance(key, str) and key and isinstance(title, str) and title.strip():
        titles[key] = title.strip()


def _title_for(source_id: object, explicit: object) -> str | None:
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    titles = _open_titles.get()
    if titles and isinstance(source_id, str):
        return titles.get(source_id)
    return None


def _log_marks(fetched: int, total: int) -> None:
    log_event(
        logger,
        "expert_chat.marks_fetched",
        dataset=EVENT_DATASET_EXPERT_CHAT,
        outcome="success",
        fields={"marks": {"fetched": fetched, "total": total}},
    )
