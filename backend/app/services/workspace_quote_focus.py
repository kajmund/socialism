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


def matching_quote(text: str, quote: str) -> str | None:
    """Longest verbatim word run from the requested quote that the document contains."""
    words = _normalized(quote).split()
    haystack = _normalized(text)
    if not words or not haystack:
        return None
    if " ".join(words) in haystack:
        return " ".join(quote.split())
    best = ""
    for start in range(len(words)):
        phrase = ""
        for word in words[start:]:
            phrase = word if not phrase else f"{phrase} {word}"
            if phrase not in haystack:
                break
            if len(phrase) > len(best):
                best = phrase
    if len(best) < 6:
        return None
    return best


def _locate_quote(data: bytes, quote: str) -> tuple[int, list[dict[str, float]], str] | None:
    words = _normalized(quote).split()
    candidates = [" ".join(words)]
    for end in range(len(words) - 1, 0, -1):
        if len(candidates) >= 8:
            break
        candidates.append(" ".join(words[:end]))
    for start in range(1, len(words)):
        if len(candidates) >= 16:
            break
        candidates.append(" ".join(words[start:]))
    with pdfplumber.open(BytesIO(data)) as pdf:
        for candidate in candidates:
            if len(candidate) < 6:
                continue
            located = first_quote_page(pdf, candidate)
            if located is not None:
                page, rects = located
                return page, rects, candidate
    return None


async def _pdf_anchor(stored: dict, quote: str) -> dict:
    data, _mime = await get_object(stored["bucket"], stored["key"])
    located = await asyncio.to_thread(_locate_quote, data, quote)
    if located is None:
        raise HTTPException(status_code=422, detail="quote_not_located")
    page, rects, exact = located
    return {"anchor_type": "text", "page_number": page, "locator": f"page:{page}",
            "exact_text": exact, "rects": rects}


async def _workspace(session: AsyncSession, workspace_id: str, user_id: str):
    user = await session.get(UserAccount, user_id, populate_existing=True)
    if user is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    return await require_workspace(session, workspace_id, user)


async def focus_passage(context, arguments: dict) -> dict:
    args = FocusPassageArguments.model_validate(arguments)
    requested = " ".join(args.quote.split())
    session = context.session
    workspace_id, user_id = context.workspace.id, context.user.id
    source = await require_source(session, context.workspace, args.source_id, member=False)
    quote = matching_quote(source.extracted_text or "", requested)
    if quote is None:
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
