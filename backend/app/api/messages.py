"""Campaign message library + Budskapsverkstad generation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Message
from app.database.session import get_session
from app.llm.message_gen import (
    generate_message_variants,
    normalize_url,
    source_domain,
    summarize_url_content,
)
from app.schemas.domain import (
    GenerateVariantsRequest,
    GenerateVariantsResponse,
    MessageCreate,
    MessageOut,
    MessageType,
    MessageUpdate,
    SummarizeUrlRequest,
    SummarizeUrlResponse,
    format_date,
    new_message_id,
)
from app.serializers import utcnow
from app.services.prompt_store import require_active_prompts

router = APIRouter(prefix="/messages", tags=["messages"])


def _serialize(row: Message) -> MessageOut:
    return MessageOut(
        id=row.id,
        type=row.type,  # type: ignore[arg-type]
        title=row.title,
        body=row.body,
        source_url=row.source_url,
        metadata=dict(row.metadata_ or {}),
        created_at=format_date(row.created_at) if row.created_at else "",
    )


async def _get_message(session: AsyncSession, message_id: str) -> Message:
    row = await session.get(Message, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return row


@router.get("", response_model=list[MessageOut])
async def list_messages(
    q: str | None = Query(default=None),
    type: MessageType | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    stmt = select(Message).order_by(Message.created_at.desc())
    if type is not None:
        stmt = stmt.where(Message.type == type)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Message.title.ilike(like), Message.body.ilike(like)))
    result = await session.execute(stmt)
    return [_serialize(row) for row in result.scalars().all()]


@router.post("/summarize-url", response_model=SummarizeUrlResponse)
async def summarize_url(
    body: SummarizeUrlRequest,
    session: AsyncSession = Depends(get_session),
) -> SummarizeUrlResponse:
    url = normalize_url(body.url)
    prompts = await require_active_prompts(session)
    try:
        summary = await summarize_url_content(url, body.message_type, prompts=prompts)
    except Exception as exc:  # noqa: BLE001 — surface fetch/LLM errors as 400
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SummarizeUrlResponse(
        summary=summary,
        source_url=url,
        source_domain=source_domain(url),
    )


@router.post("/generate-variants", response_model=GenerateVariantsResponse)
async def generate_variants(
    body: GenerateVariantsRequest,
    session: AsyncSession = Depends(get_session),
) -> GenerateVariantsResponse:
    prompts = await require_active_prompts(session)
    try:
        variants = await generate_message_variants(body, prompts=prompts)
    except Exception as exc:  # noqa: BLE001 — surface generation errors as 400
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GenerateVariantsResponse(variants=variants)


@router.get("/{message_id}", response_model=MessageOut)
async def get_message(
    message_id: str,
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    return _serialize(await _get_message(session, message_id))


@router.post("", response_model=MessageOut, status_code=201)
async def create_message(
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    message_id = body.id or new_message_id()
    if await session.get(Message, message_id) is not None:
        raise HTTPException(status_code=409, detail="Message id already exists")
    row = Message(
        id=message_id,
        type=body.type,
        title=body.title,
        body=body.body,
        source_url=(normalize_url(body.source_url) if body.source_url else None),
        metadata_=dict(body.metadata or {}),
        created_at=utcnow(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.patch("/{message_id}", response_model=MessageOut)
async def update_message(
    message_id: str,
    body: MessageUpdate,
    session: AsyncSession = Depends(get_session),
) -> MessageOut:
    row = await _get_message(session, message_id)
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        row.title = data["title"]
    if "body" in data and data["body"] is not None:
        row.body = data["body"]
    if "type" in data and data["type"] is not None:
        row.type = data["type"]
    if "source_url" in data:
        row.source_url = normalize_url(data["source_url"]) if data["source_url"] else None
    if "metadata" in data and data["metadata"] is not None:
        row.metadata_ = dict(data["metadata"])
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.delete("/{message_id}", status_code=204)
async def delete_message(
    message_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_message(session, message_id)
    await session.delete(row)
    await session.commit()
