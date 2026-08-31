"""Campaign message library + Budskapsverkstad generation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.message_images import router as message_images_router
from app.api.message_images import message_image_sha256
from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access, require_user_kund_id
from app.database.models import Message, Projekt, UserAccount
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
from app.services.image_cache import get_entry
from app.services.kund_store import DEFAULT_PROJEKT_SLUG, default_os_project_id
from app.services.prompt_store import require_active_prompts

router = APIRouter(prefix="/messages", tags=["messages"])
router.include_router(message_images_router)


def _serialize(row: Message) -> MessageOut:
    meta = dict(row.metadata_ or {})
    digest = message_image_sha256(meta)
    caption: str | None = None
    if digest:
        entry = get_entry(digest)
        if entry is not None:
            caption = str(entry.get("caption") or "") or None
    return MessageOut(
        id=row.id,
        type=row.type,  # type: ignore[arg-type]
        title=row.title,
        body=row.body,
        source_url=row.source_url,
        metadata=meta,
        image_sha256=digest,
        image_caption=caption,
        created_at=format_date(row.created_at) if row.created_at else "",
        project_id=row.project_id,
    )


async def _get_message(session: AsyncSession, message_id: str) -> Message:
    row = await session.get(Message, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return row


async def _assert_message_access(
    session: AsyncSession,
    user: UserAccount,
    message: Message,
) -> None:
    projekt = await session.get(Projekt, message.project_id)
    assert_kund_access(user, None if projekt is None else projekt.customer_id)


async def _project_id_for_create(session: AsyncSession, user: UserAccount) -> int:
    if user.role == "admin":
        return await default_os_project_id(session)
    kund_id = require_user_kund_id(user)
    result = await session.execute(
        select(Projekt).where(
            Projekt.customer_id == kund_id,
            Projekt.slug == DEFAULT_PROJEKT_SLUG,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=403, detail="kund_access_denied")
    return int(row.id)


@router.get("", response_model=list[MessageOut])
async def list_messages(
    q: str | None = Query(default=None),
    type: MessageType | None = Query(default=None),
    project_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[MessageOut]:
    stmt = select(Message).order_by(Message.created_at.desc())
    if user.role != "admin":
        kund_id = require_user_kund_id(user)
        stmt = stmt.join(Projekt, Message.project_id == Projekt.id).where(
            Projekt.customer_id == kund_id
        )
    if project_id is not None:
        stmt = stmt.where(Message.project_id == project_id)
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
    _user: UserAccount = Depends(get_current_user),
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
    _user: UserAccount = Depends(get_current_user),
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
    user: UserAccount = Depends(get_current_user),
) -> MessageOut:
    row = await _get_message(session, message_id)
    await _assert_message_access(session, user, row)
    return _serialize(row)


@router.post("", response_model=MessageOut, status_code=201)
async def create_message(
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> MessageOut:
    message_id = body.id or new_message_id()
    if await session.get(Message, message_id) is not None:
        raise HTTPException(status_code=409, detail="Message id already exists")
    metadata = dict(body.metadata or {})
    digest = message_image_sha256(metadata)
    if digest and get_entry(digest) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Image cache entry {digest!r} not found — upload the image first",
        )
    row = Message(
        id=message_id,
        project_id=await _project_id_for_create(session, user),
        type=body.type,
        title=body.title,
        body=body.body,
        source_url=(normalize_url(body.source_url) if body.source_url else None),
        metadata_=metadata,
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
    user: UserAccount = Depends(get_current_user),
) -> MessageOut:
    row = await _get_message(session, message_id)
    await _assert_message_access(session, user, row)
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
        merged = dict(row.metadata_ or {})
        merged.update(dict(data["metadata"]))
        digest = message_image_sha256(merged)
        if digest and get_entry(digest) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Image cache entry {digest!r} not found — upload the image first",
            )
        row.metadata_ = merged
    meta = dict(row.metadata_ or {})
    if not str(row.body or "").strip() and not message_image_sha256(meta):
        raise HTTPException(
            status_code=422,
            detail="body or metadata.image_sha256 is required",
        )
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


@router.delete("/{message_id}", status_code=204)
async def delete_message(
    message_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> None:
    row = await _get_message(session, message_id)
    await _assert_message_access(session, user, row)
    await session.delete(row)
    await session.commit()
