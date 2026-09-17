"""Customer-scoped SME Messenger inbox and panel conversations."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
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
from app.llm.chat import reply_as_persona
from app.schemas.sme import (
    SmeInboxItem,
    SmeMessageOut,
    SmePanelMessageCreate,
    SmeReadOut,
    SmeThreadType,
)
from app.serializers import persona_initials, profile_from_dict, utcnow
from app.services.dd.default_experts import ensure_default_expert_personas
from app.services.district_context import area_block_for_name
from app.services.persona_chat import (
    expert_memory_context,
    remember_expert_chat_turn,
)
from app.services.prompt_store import require_prompts_for_persona

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
    if filter in {"groups", "unread"}:
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
    panel = await _require_panel(session, panel_id, customer_id)
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    experts = [member.persona for member in panel.members if member.persona]
    if not experts:
        raise HTTPException(status_code=400, detail="Expert panel has no linked experts")

    previous_result = await session.execute(
        select(SmePanelMessage)
        .where(SmePanelMessage.population_id == panel_id)
        .order_by(SmePanelMessage.id.asc())
    )
    previous = list(previous_result.scalars().all())
    now = utcnow()
    user_row = SmePanelMessage(
        customer_id=customer_id,
        population_id=panel_id,
        role="user",
        content=message,
        created_at=now,
    )
    session.add(user_row)
    await session.flush()

    reply_calls = []
    for expert in experts:
        history = [
            (row.role, row.content)
            for row in previous
            if row.role == "user" or row.persona_id == expert.id
        ]
        profile = profile_from_dict(expert.profile, expert.name)
        prompts = await require_prompts_for_persona(session, expert)
        area_block = await area_block_for_name(session, profile.ort or expert.district)
        memory_context = await expert_memory_context(expert, message, prompts)
        reply_calls.append(
            reply_as_persona(
                profile,
                "interview",
                history,
                message,
                prompts=prompts,
                area_block=area_block,
                extra_system=memory_context,
                profile_kind="expert",
            )
        )
    replies = await asyncio.gather(*reply_calls)

    created: list[tuple[SmePanelMessage, str | None]] = [(user_row, None)]
    for expert, reply in zip(experts, replies, strict=True):
        reply_row = SmePanelMessage(
            customer_id=customer_id,
            population_id=panel_id,
            role="assistant",
            persona_id=expert.id,
            content=reply,
            created_at=utcnow(),
        )
        session.add(reply_row)
        await session.flush()
        created.append((reply_row, expert.name))
        await remember_expert_chat_turn(
            expert,
            message=message,
            reply=reply,
            image_sha256=None,
        )
    await session.commit()
    return [
        SmeMessageOut(
            id=row.id,
            role=row.role,  # type: ignore[arg-type]
            content=row.content,
            created_at=row.created_at,
            persona_id=row.persona_id,
            persona_name=name,
        )
        for row, name in created
    ]


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
    cursor_result = await session.execute(
        select(SmeReadCursor).where(
            SmeReadCursor.user_id == user.id,
            SmeReadCursor.thread_type == thread_type,
            SmeReadCursor.thread_id == thread_id,
        )
    )
    cursor = cursor_result.scalar_one_or_none()
    if cursor is None:
        cursor = SmeReadCursor(
            user_id=user.id,
            thread_type=thread_type,
            thread_id=thread_id,
            last_read_message_id=last_id,
            updated_at=utcnow(),
        )
        session.add(cursor)
    else:
        cursor.last_read_message_id = last_id
        cursor.updated_at = utcnow()
    await session.commit()
    return SmeReadOut(last_read_message_id=last_id)
