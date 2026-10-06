"""Locate an exact phrase and cite it so the document view can highlight it."""

import asyncio
from io import BytesIO

import pdfplumber
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.services.object_storage import get_object
from app.services.pdf_quote_anchors import _normalized, first_quote_page
from app.services.workspace.service import add_source, require_source, require_workspace
from app.services.workspace.sources import citation, reference_out, source_version
from app.services.workspace.tool_arguments import FocusPassageArguments


def _contains(text: str, quote: str) -> bool:
    return _normalized(quote) in _normalized(text)


def _first_page(data: bytes, quote: str) -> tuple[int, list[dict[str, float]]] | None:
    with pdfplumber.open(BytesIO(data)) as pdf:
        return first_quote_page(pdf, quote)


async def _pdf_anchor(stored: dict, quote: str) -> dict:
    data, _mime = await get_object(stored["bucket"], stored["key"])
    located = await asyncio.to_thread(_first_page, data, quote)
    if located is None:
        raise HTTPException(status_code=422, detail="quote_not_located")
    page, rects = located
    return {"anchor_type": "text", "page_number": page, "locator": f"page:{page}",
            "exact_text": quote, "rects": rects}


async def _workspace(session: AsyncSession, workspace_id: str, user_id: str):
    user = await session.get(UserAccount, user_id, populate_existing=True)
    if user is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    return await require_workspace(session, workspace_id, user)


async def focus_passage(context, arguments: dict) -> dict:
    args = FocusPassageArguments.model_validate(arguments)
    quote = " ".join(args.quote.split())
    session = context.session
    workspace_id, user_id = context.workspace.id, context.user.id
    source = await require_source(session, context.workspace, args.source_id, member=False)
    if not _contains(source.extracted_text or "", quote):
        raise HTTPException(status_code=422, detail="quote_not_in_source")
    source = await add_source(session, context.workspace, args.source_id)
    stored = {"id": source.id, "bucket": source.bucket, "key": source.object_key,
              "content_type": source.content_type, "version": source_version(source),
              "filename": source.filename}
    if source.content_type == "application/pdf":
        context.operation.external_started = True
        await session.commit()
        anchor = await _pdf_anchor(stored, quote)
    else:
        anchor = {"anchor_type": "text", "page_number": None, "locator": "passage",
                  "exact_text": quote, "rects": []}
    workspace = await _workspace(session, workspace_id, user_id)
    source = await require_source(session, workspace, stored["id"])
    if source_version(source) != stored["version"]:
        raise HTTPException(status_code=409, detail="workspace_source_changed_during_read")
    ref = await citation(session, workspace, kind="underlag", source_id=source.id, version=stored["version"],
                         anchor=anchor, snapshot={"title": stored["filename"], "excerpt": quote})
    return {"status": "completed", **reference_out(ref)}
