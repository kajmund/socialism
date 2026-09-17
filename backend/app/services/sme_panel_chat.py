"""SME panel turns: per-expert tools, no research initiation, DB-serialized."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.database.models import (
    Persona,
    Population,
    PopulationMember,
    SmePanelMessage,
    UserAccount,
)
from app.llm.chat import reply_as_persona
from app.schemas.sme import SmeMessageOut
from app.serializers import profile_from_dict, utcnow
from app.services.district_context import area_block_for_name
from app.services.expert_tools import panel_chat_tools
from app.services.persona_chat import expert_memory_context, remember_expert_chat_turn
from app.services.prompt_store import require_prompts_for_persona
from app.services.sme_panel_lease import (
    acquire_panel_lease,
    panel_lease_still_held,
    release_panel_lease,
)


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


def _message_out(row: SmePanelMessage, persona_name: str | None) -> SmeMessageOut:
    return SmeMessageOut(
        id=row.id,
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        created_at=row.created_at,
        persona_id=row.persona_id,
        persona_name=persona_name,
    )


async def run_panel_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    panel_id: int,
    customer_id: int,
    user: UserAccount,
    message: str,
) -> list[SmeMessageOut]:
    del user
    text = message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")

    token = uuid4().hex
    async with session_factory() as session:
        await _require_panel(session, panel_id, customer_id)
        await session.commit()
    fence = await acquire_panel_lease(session_factory, panel_id, token=token)
    try:
        async with session_factory() as session:
            panel = await _require_panel(session, panel_id, customer_id)
            experts = [member.persona for member in panel.members if member.persona]
            if not experts:
                raise HTTPException(status_code=400, detail="Expert panel has no linked experts")
            previous_result = await session.execute(
                select(SmePanelMessage)
                .where(SmePanelMessage.population_id == panel_id)
                .order_by(SmePanelMessage.id.asc())
            )
            previous = list(previous_result.scalars().all())
            reply_inputs: list[
                tuple[Persona, list[tuple[str, str]], object, dict[str, str], str, str]
            ] = []
            for expert in experts:
                history = [
                    (row.role, row.content)
                    for row in previous
                    if row.role == "user" or row.persona_id == expert.id
                ]
                profile = profile_from_dict(expert.profile, expert.name)
                prompts = await require_prompts_for_persona(session, expert)
                area_block = await area_block_for_name(session, profile.ort or expert.district)
                memory_context = await expert_memory_context(expert, text, prompts)
                reply_inputs.append((expert, history, profile, prompts, area_block, memory_context))
            await session.commit()

        replies = await asyncio.gather(
            *[
                reply_as_persona(
                    profile,
                    "interview",
                    history,
                    text,
                    prompts=prompts,
                    area_block=area_block,
                    extra_system=memory_context,
                    profile_kind="expert",
                    tools=panel_chat_tools(expert.tools),
                )
                for expert, history, profile, prompts, area_block, memory_context in reply_inputs
            ]
        )

        async with session_factory() as session:
            if not await panel_lease_still_held(
                session, panel_id, token=token, fence=fence
            ):
                raise HTTPException(status_code=409, detail="stale_panel_turn")
            now = utcnow()
            user_row = SmePanelMessage(
                customer_id=customer_id,
                population_id=panel_id,
                role="user",
                content=text,
                created_at=now,
            )
            session.add(user_row)
            await session.flush()
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
                    message=text,
                    reply=reply,
                    image_sha256=None,
                    source="panel_chat",
                )
            await session.commit()
        return [_message_out(row, name) for row, name in created]
    finally:
        async with session_factory() as session:
            await release_panel_lease(session, panel_id, token=token, fence=fence)
            await session.commit()
