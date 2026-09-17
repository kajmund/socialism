"""Customer-scoped SME Messenger inbox and panel conversations."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.auth.scope import require_user_kund_id
from app.database.models import (
    Kund,
    Persona,
    PersonaMessage,
    Population,
    PopulationMember,
    SmePanelMessage,
    SmeReadCursor,
    UserAccount,
)
from app.database.session import get_session
from app.schemas.sme import (
    SmeExpertTurnOut,
    SmeInboxItem,
    SmeMessageOut,
    SmePanelMessageCreate,
    SmeReadOut,
    SmeThreadType,
)
from app.serializers import persona_initials, utcnow
from app.services import jobs as jobs_service
from app.services.dd.default_experts import ensure_default_expert_personas
from app.services.sme_expert_turns import get_owned_expert_turn, serialize_expert_turn
from app.services.sme_panel_chat import run_panel_message

router = APIRouter(prefix="/sme", tags=["sme"])


async def _require_sme_customer(
    session: AsyncSession,
    user: UserAccount,
) -> int:
    customer_id = require_user_kund_id(user)
    kund = await session.get(Kund, customer_id)
    if kund is None or kund.product != "sme":
        raise HTTPException(status_code=403, detail="sme_product_required")
    return customer_id


def _library_message(persona_id: str) -> tuple[object, ...]:
    return (
        PersonaMessage.persona_id == persona_id,
        PersonaMessage.mode == "interview",
        PersonaMessage.run_id.is_(None),
    )


async def _read_cursors(
    session: AsyncSession,
    user_id: str,
) -> dict[tuple[str, str], int]:
    result = await session.execute(select(SmeReadCursor).where(SmeReadCursor.user_id == user_id))
    return {
        (row.thread_type, row.thread_id): row.last_read_message_id or 0
        for row in result.scalars().all()
    }


@router.get("/inbox", response_model=list[SmeInboxItem])
async def list_inbox(
    filter: Literal["all", "unread", "groups"] = Query(default="all"),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[SmeInboxItem]:
    customer_id = await _require_sme_customer(session, user)
    await ensure_default_expert_personas(session, customer_id=customer_id)
    await session.commit()

    experts_result = await session.execute(
        select(Persona)
        .where(Persona.customer_id == customer_id, Persona.kind == "expert")
        .order_by(Persona.name.asc())
    )
    experts = list(experts_result.scalars().all())
    expert_ids = [row.id for row in experts]
    expert_messages: dict[str, list[PersonaMessage]] = defaultdict(list)
    if expert_ids:
        result = await session.execute(
            select(PersonaMessage)
            .where(
                PersonaMessage.persona_id.in_(expert_ids),
                PersonaMessage.mode == "interview",
                PersonaMessage.run_id.is_(None),
            )
            .order_by(PersonaMessage.id.asc())
        )
        for message in result.scalars().all():
            expert_messages[message.persona_id].append(message)

    panels_result = await session.execute(
        select(Population)
        .where(
            Population.customer_id == customer_id,
            Population.kind == "expert_panel",
        )
        .options(selectinload(Population.members).selectinload(PopulationMember.persona))
        .order_by(Population.name.asc())
    )
    panels = list(panels_result.scalars().unique().all())
    panel_ids = [row.id for row in panels]
    panel_messages: dict[int, list[SmePanelMessage]] = defaultdict(list)
    if panel_ids:
        result = await session.execute(
            select(SmePanelMessage)
            .where(SmePanelMessage.population_id.in_(panel_ids))
            .order_by(SmePanelMessage.id.asc())
        )
        for message in result.scalars().all():
            panel_messages[message.population_id].append(message)

    cursors = await _read_cursors(session, user.id)
    items: list[SmeInboxItem] = []
    if filter != "groups":
        for expert in experts:
            messages = expert_messages[expert.id]
            last = messages[-1] if messages else None
            cursor = cursors.get(("expert", expert.id), 0)
            unread = sum(row.role == "assistant" and row.id > cursor for row in messages)
            items.append(
                SmeInboxItem(
                    thread_type="expert",
                    thread_id=expert.id,
                    name=expert.name,
                    initials=persona_initials(expert.name),
                    subtitle=expert.occ,
                    preview=last.content if last else expert.quote,
                    last_message_at=last.created_at if last else None,
                    unread_count=unread,
                )
            )
    for panel in panels:
        messages = panel_messages[panel.id]
        last = messages[-1] if messages else None
        thread_id = str(panel.id)
        cursor = cursors.get(("panel", thread_id), 0)
        unread = sum(row.role == "assistant" and row.id > cursor for row in messages)
        member_names = [
            member.persona.name if member.persona else member.name for member in panel.members
        ]
        items.append(
            SmeInboxItem(
                thread_type="panel",
                thread_id=thread_id,
                name=panel.name,
                initials=persona_initials(panel.name),
                subtitle=", ".join(member_names),
                preview=last.content if last else "",
                last_message_at=last.created_at if last else None,
                unread_count=unread,
                member_names=member_names,
            )
        )
    if filter == "unread":
        items = [item for item in items if item.unread_count > 0]
    return sorted(
        items,
        key=lambda item: (
            item.last_message_at is not None,
            item.last_message_at.isoformat() if item.last_message_at else item.name,
        ),
        reverse=True,
    )


@router.get("/panels/{panel_id}/messages", response_model=list[SmeMessageOut])
async def list_panel_messages(
    panel_id: int,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[SmeMessageOut]:
    customer_id = await _require_sme_customer(session, user)
    await _require_panel(session, panel_id, customer_id)
    result = await session.execute(
        select(SmePanelMessage, Persona.name)
        .outerjoin(Persona, Persona.id == SmePanelMessage.persona_id)
        .where(SmePanelMessage.population_id == panel_id)
        .order_by(SmePanelMessage.id.asc())
    )
    return [
        SmeMessageOut(
            id=row.id,
            role=row.role,  # type: ignore[arg-type]
            content=row.content,
            created_at=row.created_at,
            persona_id=row.persona_id,
            persona_name=persona_name,
        )
        for row, persona_name in result.all()
    ]


async def _require_panel(
    session: AsyncSession,
    panel_id: int,
    customer_id: int,
) -> Population:
    result = await session.execute(
        select(Population)
        .where(
            Population.id == panel_id,
            Population.customer_id == customer_id,
            Population.kind == "expert_panel",
        )
        .options(selectinload(Population.members).selectinload(PopulationMember.persona))
    )
    panel = result.scalar_one_or_none()
    if panel is None:
        raise HTTPException(status_code=404, detail="Expert panel not found")
    return panel


@router.post("/panels/{panel_id}/messages", response_model=list[SmeMessageOut])
async def create_panel_message(
    panel_id: int,
    body: SmePanelMessageCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[SmeMessageOut]:
    customer_id = await _require_sme_customer(session, user)
    await session.commit()
    factory = jobs_service.job_session_factory()
    if factory is None:
        raise RuntimeError("job session factory is not configured")
    return await run_panel_message(
        factory,
        panel_id=panel_id,
        customer_id=customer_id,
        user=user,
        message=body.message,
    )


@router.get("/expert-turns/{request_id}", response_model=SmeExpertTurnOut)
async def get_expert_turn(
    request_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> SmeExpertTurnOut:
    customer_id = await _require_sme_customer(session, user)
    turn = await get_owned_expert_turn(
        session,
        request_id,
        customer_id=customer_id,
        user_id=user.id,
    )
    if turn is None:
        raise HTTPException(status_code=404, detail="Expert turn not found")
    return await serialize_expert_turn(session, turn)


@router.post(
    "/threads/{thread_type}/{thread_id}/read",
    response_model=SmeReadOut,
)
async def mark_thread_read(
    thread_type: SmeThreadType,
    thread_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> SmeReadOut:
    customer_id = await _require_sme_customer(session, user)
    if thread_type == "expert":
        expert = await session.get(Persona, thread_id)
        if expert is None or expert.customer_id != customer_id or expert.kind != "expert":
            raise HTTPException(status_code=404, detail="Expert not found")
        result = await session.execute(
            select(PersonaMessage.id)
            .where(*_library_message(thread_id))
            .order_by(PersonaMessage.id.desc())
            .limit(1)
        )
    else:
        try:
            panel_id = int(thread_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Expert panel not found") from exc
        await _require_panel(session, panel_id, customer_id)
        result = await session.execute(
            select(SmePanelMessage.id)
            .where(SmePanelMessage.population_id == panel_id)
            .order_by(SmePanelMessage.id.desc())
            .limit(1)
        )
    last_id = result.scalar_one_or_none()
    now = utcnow()
    cursor_update = (
        update(SmeReadCursor)
        .where(
            SmeReadCursor.user_id == user.id,
            SmeReadCursor.thread_type == thread_type,
            SmeReadCursor.thread_id == thread_id,
        )
        .values(last_read_message_id=last_id, updated_at=now)
    )
    updated = await session.execute(cursor_update)
    if updated.rowcount == 0:
        try:
            async with session.begin_nested():
                session.add(
                    SmeReadCursor(
                        user_id=user.id,
                        thread_type=thread_type,
                        thread_id=thread_id,
                        last_read_message_id=last_id,
                        updated_at=now,
                    )
                )
                await session.flush()
        except IntegrityError:
            await session.execute(cursor_update)
    await session.commit()
    return SmeReadOut(last_read_message_id=last_id)
