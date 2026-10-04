"""Verify manual PDF selections against original characters outside SQL waits."""

import asyncio
from dataclasses import dataclass
from io import BytesIO
from math import isfinite

import pdfplumber
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Kund, StoredObject, UserAccount
from app.database.transaction_state import has_pending_writes
from app.database.workspaces import Workspace, WorkspaceChat, WorkspaceMembership
from app.database.workspace_models import VoiceWorkspace, WorkspaceReference, WorkspaceSource
from app.schemas.workspace import WorkspaceSelection, WorkspaceState
from app.services.object_storage import get_object
from app.services.pdf_quote_anchors import _normalized
from app.services.underlag_schemas import DocumentKnowledgeAnchorWrite
from app.services.workspace.service import require_reference, require_source, require_workspace
from app.services.workspace.sources import citation, source_version


@dataclass(frozen=True)
class SelectionInput:
    workspace_id: str
    actor_id: str
    binding: tuple[str, str, int, str]
    source_id: str
    bucket: str
    key: str
    version: str
    mime: str


def _binding(workspace: VoiceWorkspace) -> tuple[str, str, int, str]:
    return workspace.workspace_id, workspace.chat_id, workspace.customer_id, workspace.owner_user_id


def _anchor_equal(anchor: DocumentKnowledgeAnchorWrite, reference: WorkspaceReference) -> bool:
    values = anchor.model_dump()
    return all(value == reference.anchor.get(key, [] if key == "rects" else None) for key, value in values.items())


def _verified_anchor(anchor: DocumentKnowledgeAnchorWrite, reference: WorkspaceReference) -> bool:
    return reference.snapshot.get("selection_verified") is True and _anchor_equal(anchor, reference)


def _parent_quote(reference: WorkspaceReference, anchor: DocumentKnowledgeAnchorWrite) -> None:
    quote = anchor.exact_text or ""
    if (not quote or _normalized(quote) not in _normalized(reference.snapshot.get("excerpt") or "")
            or any(getattr(anchor, field) != reference.anchor.get(field) for field in ("page_number", "locator"))):
        raise HTTPException(status_code=409, detail="selection_anchor_stale")


def _rectangles(anchor: DocumentKnowledgeAnchorWrite) -> list[tuple[float, float, float, float]]:
    if (anchor.anchor_type != "text" or anchor.page_number is None or not anchor.rects
            or anchor.locator != f"page:{anchor.page_number}"):
        raise HTTPException(status_code=409, detail="selection_anchor_stale")
    rects = [(rect.x, rect.y, rect.x + rect.width, rect.y + rect.height) for rect in anchor.rects]
    if any(not all(isfinite(value) for value in rect) or not (0 <= rect[0] < rect[2] <= 1 and 0 <= rect[1] < rect[3] <= 1)
           for rect in rects):
        raise HTTPException(status_code=409, detail="selection_anchor_stale")
    return rects


def selected_pdf_quote(data: bytes, anchor: DocumentKnowledgeAnchorWrite) -> str:
    rects = _rectangles(anchor)
    with pdfplumber.open(BytesIO(data)) as pdf:
        if anchor.page_number > len(pdf.pages):
            raise HTTPException(status_code=409, detail="selection_anchor_stale")
        page = pdf.pages[anchor.page_number - 1]
        if not page.width or not page.height:
            raise HTTPException(status_code=409, detail="selection_anchor_stale")
        chars = [char for char in page.chars if any(
            left <= (char["x0"] + char["x1"]) / (2 * page.width) <= right
            and top <= (char["top"] + char["bottom"]) / (2 * page.height) <= bottom
            for left, top, right, bottom in rects)]
        quote = pdfplumber.utils.extract_text(chars, x_tolerance=3, y_tolerance=3) if chars else ""
    if not quote or _normalized(quote) != _normalized(anchor.exact_text or ""):
        raise HTTPException(status_code=409, detail="selection_anchor_stale")
    return " ".join(quote.split())


async def _selection_source(session, workspace, selection):
    reference = await require_reference(session, workspace, selection.reference_id) if selection.reference_id else None
    if reference is not None and reference.kind != "underlag":
        return None, reference
    source_id = selection.source_id or (reference.source_id if reference else None)
    source = await require_source(session, workspace, source_id) if source_id else None
    if reference is not None and source is not None:
        if reference.source_id != source.id:
            raise HTTPException(status_code=409, detail="document_anchor_source_conflict")
        if reference.source_version != source_version(source):
            raise HTTPException(status_code=409, detail="workspace_reference_stale")
    return source, reference


async def _fresh_source(session: AsyncSession, original: SelectionInput) -> tuple[VoiceWorkspace, StoredObject]:
    actor = await session.get(UserAccount, original.actor_id, populate_existing=True)
    workspace = await session.get(VoiceWorkspace, original.workspace_id, populate_existing=True)
    if actor is None or workspace is None or _binding(workspace) != original.binding:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    customer = await session.get(Kund, workspace.customer_id, populate_existing=True)
    chat = await session.get(WorkspaceChat, workspace.chat_id, populate_existing=True)
    parent = await session.get(Workspace, workspace.workspace_id, populate_existing=True)
    if customer is None or chat is None or parent is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    await session.get(WorkspaceMembership, (workspace.workspace_id, actor.id), populate_existing=True)
    member = await session.get(WorkspaceSource, (workspace.id, original.source_id), populate_existing=True)
    if member is None:
        raise HTTPException(status_code=404, detail="workspace_source_not_found")
    workspace = await require_workspace(session, workspace.id, actor)
    source = await require_source(session, workspace, original.source_id)
    if (source_version(source), source.bucket, source.object_key, source.content_type) != (
            original.version, original.bucket, original.key, original.mime):
        raise HTTPException(status_code=409, detail="workspace_reference_stale")
    return workspace, source


async def prepare_pdf_selection(session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount,
                                state: WorkspaceState | None) -> VoiceWorkspace:
    if has_pending_writes(session):
        raise RuntimeError("PDF selection verification requires a clean transaction")
    selection = state.selection if state else None
    if selection is None or selection.anchor is None:
        return workspace
    source, reference = await _selection_source(session, workspace, selection)
    if source is None or source.content_type != "application/pdf":
        return workspace
    _rectangles(selection.anchor)
    if reference is not None:
        if _verified_anchor(selection.anchor, reference):
            return workspace
        _parent_quote(reference, selection.anchor)
    original = SelectionInput(workspace.id, user.id, _binding(workspace), source.id,
        source.bucket, source.object_key, source_version(source), source.content_type)
    await session.rollback()
    data, _mime = await get_object(original.bucket, original.key)
    quote = await asyncio.to_thread(selected_pdf_quote, data, selection.anchor)
    workspace, source = await _fresh_source(session, original)
    if selection.reference_id:
        reference = await require_reference(session, workspace, selection.reference_id)
        _parent_quote(reference, selection.anchor)
    selection.anchor.exact_text = quote
    reference = await citation(session, workspace, kind="underlag", source_id=source.id,
        version=source_version(source), anchor=selection.anchor.model_dump(),
        snapshot={"title": source.filename, "excerpt": quote, "selection_verified": True})
    selection.reference_id = reference.id
    return workspace


async def validate_pdf_reference(session: AsyncSession, workspace: VoiceWorkspace, reference: WorkspaceReference,
                                 anchor: DocumentKnowledgeAnchorWrite) -> None:
    if reference.kind != "underlag":
        return
    source = await require_source(session, workspace, reference.source_id)
    if source.content_type == "application/pdf":
        _rectangles(anchor)
        if not _verified_anchor(anchor, reference):
            raise HTTPException(status_code=409, detail="selection_anchor_stale")


async def validate_source_selection(session: AsyncSession, workspace: VoiceWorkspace, selection: WorkspaceSelection) -> None:
    source, reference = await _selection_source(session, workspace, selection)
    if selection.anchor is None:
        raise HTTPException(status_code=422, detail="selection_anchor_required")
    if source is None:
        raise HTTPException(status_code=409, detail="document_anchor_source_conflict")
    if source.content_type == "application/pdf":
        _rectangles(selection.anchor)
        if reference is None or not _verified_anchor(selection.anchor, reference):
            raise HTTPException(status_code=409, detail="selection_anchor_stale")
        return
    exact = selection.anchor.exact_text or ""
    if not exact or _normalized(exact) not in _normalized(source.extracted_text or ""):
        raise HTTPException(status_code=409, detail="selection_anchor_stale")
    reference = await citation(session, workspace, kind="underlag", source_id=source.id,
        version=source_version(source), anchor=selection.anchor.model_dump(), snapshot={"title": source.filename, "excerpt": exact})
    selection.reference_id = reference.id
