"""Comments anchored to a marked passage. The key is canonical JSON so the browser can rebuild it."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspacePassageComment, WorkspaceReference, WorkspaceSource
from app.schemas.workspace import PassageCommentPatch, PassageCommentWrite
from app.services.underlag_schemas import DocumentKnowledgeAnchorWrite
from app.services.workspace.mark_author import marked_author


def passage_comment_key(source_id: str, anchor: dict) -> str:
    rects = anchor.get("rects") or []
    if rects:
        basis: object = [[_millionths(_rect(rect, name)) for name in ("x", "y", "width", "height")] for rect in rects]
    else:
        basis = [_words(anchor.get("prefix_text")), _words(anchor.get("exact_text"))]
    return json.dumps([source_id, anchor.get("page_number"), basis], separators=(",", ":"), ensure_ascii=False)


def comment_out(row: WorkspacePassageComment) -> dict:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "passage_key": row.passage_key,
        "anchor": row.anchor,
        "author_id": row.author_user_id,
        "author_kind": row.author_kind,
        "expert_id": row.expert_id,
        "author_name": row.author_name,
        "body": row.body,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def list_passage_comments(session: AsyncSession, workspace: VoiceWorkspace) -> list[dict]:
    rows = list((await session.scalars(select(WorkspacePassageComment).where(
        WorkspacePassageComment.workspace_id == workspace.id).order_by(WorkspacePassageComment.created_at))).all())
    return [comment_out(row) for row in rows]


async def create_passage_comment(session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount, body: PassageCommentWrite) -> dict:
    if await session.get(WorkspaceSource, (workspace.id, body.source_id)) is None:
        raise HTTPException(status_code=404, detail="workspace_source_not_found")
    anchor = DocumentKnowledgeAnchorWrite.model_validate(body.anchor).model_dump(mode="json")
    row = WorkspacePassageComment(
        id=str(uuid4()), workspace_id=workspace.id, source_id=body.source_id,
        passage_key=passage_comment_key(body.source_id, anchor), anchor=anchor,
        author_user_id=user.id, author_kind="user", author_name=_author_name(user), body=body.body,
    )
    session.add(row)
    await session.flush()
    return comment_out(row)


async def create_expert_passage_comment(
    session: AsyncSession, workspace: VoiceWorkspace, *, source_id: str, anchor: dict,
    expert_id: str, author_name: str, body: str,
) -> dict:
    key = passage_comment_key(source_id, anchor)
    existing = await session.scalar(select(WorkspacePassageComment).where(
        WorkspacePassageComment.workspace_id == workspace.id,
        WorkspacePassageComment.passage_key == key,
        WorkspacePassageComment.expert_id == expert_id,
        WorkspacePassageComment.body == body,
    ))
    if existing is not None:
        return comment_out(existing)
    row = WorkspacePassageComment(
        id=str(uuid4()), workspace_id=workspace.id, source_id=source_id, passage_key=key, anchor=anchor,
        author_user_id=None, author_kind="expert", expert_id=expert_id, author_name=author_name, body=body,
    )
    session.add(row)
    await session.flush()
    return comment_out(row)


async def update_passage_comment(session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount, *, comment_id: str, body: PassageCommentPatch) -> dict:
    row = await _own_comment(session, workspace, user, comment_id)
    row.body = body.body
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return comment_out(row)


async def delete_passage_comment(session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount, comment_id: str) -> list[str]:
    row = await _workspace_comment(session, workspace, comment_id)
    if not _reader_may_delete(row, user):
        raise HTTPException(status_code=403, detail="passage_comment_forbidden")
    await session.delete(row)
    await session.flush()
    return await _release_mark(session, workspace, row)


async def _own_comment(session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount, comment_id: str) -> WorkspacePassageComment:
    row = await _workspace_comment(session, workspace, comment_id)
    if row.author_kind != "user" or row.author_user_id != user.id:
        raise HTTPException(status_code=403, detail="passage_comment_forbidden")
    return row


async def _workspace_comment(session: AsyncSession, workspace: VoiceWorkspace, comment_id: str) -> WorkspacePassageComment:
    row = await session.get(WorkspacePassageComment, comment_id)
    if row is None or row.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="passage_comment_not_found")
    return row


def _reader_may_delete(row: WorkspacePassageComment, user: UserAccount) -> bool:
    if row.author_kind == "expert":
        return True
    return row.author_kind == "user" and row.author_user_id == user.id


async def _release_mark(session: AsyncSession, workspace: VoiceWorkspace, row: WorkspacePassageComment) -> list[str]:
    """The mark belongs to the comment. It stays while that author still has another comment on the passage."""
    author_id = row.expert_id if row.author_kind == "expert" else row.author_user_id
    if not author_id or await _author_still_comments(session, row, author_id):
        return []
    refs = list(await session.scalars(select(WorkspaceReference).where(
        WorkspaceReference.workspace_id == workspace.id,
        WorkspaceReference.source_id == row.source_id,
        WorkspaceReference.kind == "underlag",
    )))
    removed: list[str] = []
    for ref in refs:
        author = marked_author(ref.snapshot)
        if author is None or author["kind"] != row.author_kind or author["id"] != author_id:
            continue
        if passage_comment_key(row.source_id, ref.anchor or {}) != row.passage_key:
            continue
        removed.append(ref.id)
        await session.delete(ref)
    if removed:
        await session.flush()
    return removed


async def _author_still_comments(session: AsyncSession, row: WorkspacePassageComment, author_id: str) -> bool:
    author = WorkspacePassageComment.expert_id if row.author_kind == "expert" else WorkspacePassageComment.author_user_id
    return await session.scalar(select(WorkspacePassageComment.id).where(
        WorkspacePassageComment.workspace_id == row.workspace_id,
        WorkspacePassageComment.source_id == row.source_id,
        WorkspacePassageComment.passage_key == row.passage_key,
        WorkspacePassageComment.author_kind == row.author_kind,
        author == author_id,
    )) is not None


def _author_name(user: UserAccount) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or user.email


def _millionths(value: object) -> int:
    scaled = float(value) * 1_000_000
    return int(scaled + (0.5 if scaled >= 0 else -0.5))


def _words(value: object) -> str:
    return " ".join(str(value or "").split())


def _rect(rect: object, name: str) -> object:
    if isinstance(rect, dict):
        return rect[name]
    return getattr(rect, name)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()
