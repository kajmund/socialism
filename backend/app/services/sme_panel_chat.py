"""SME panel turns use the same expert turn as live voice, DB-serialized."""

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
from app.schemas.sme import SmeMessageOut
from app.schemas.workspace import DocumentMention
from app.serializers import utcnow
from app.services.prompt_render import prompt_template
from app.services.prompt_store import require_prompts_for_persona
from app.services.sme_group_voice import GroupVoiceSession, raised_hand_line
from app.services.sme_group_voice_turns import expert_group_reply, group_history, speaker_note
from app.services.sme_open_document import (
    load_open_workspace,
    publish_document_open,
    publish_speaker_tools,
)
from app.services.sme_panel_lease import (
    PanelLeaseHeartbeat,
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


ChannelLine = tuple[str, str | None, str]


def channel_history(
    expert_id: str,
    names: dict[str, str],
    lines: list[ChannelLine],
) -> list[tuple[str, str]]:
    """Panel transcript for one expert. Other experts stay named in the channel."""
    history: list[tuple[str, str]] = []
    for role, speaker_id, content in lines:
        if role == "assistant" and speaker_id == expert_id:
            history.append(("assistant", content))
            continue
        if role == "assistant":
            history.append(("user", f"{names.get(speaker_id or '', 'Expert')}: {content}"))
            continue
        history.append(("user", content))
    return history


def hand_aware_context(context: str, others: list[str]) -> str:
    return f"{context}\n\n{raised_hand_line(others)}".strip()


async def speakers_for_utterance(
    experts: list[Persona], utterance: str, raise_prompt: str
) -> tuple[list[Persona], set[str], GroupVoiceSession]:
    """The expert closest to the utterance speaks. Others speak only if they have something to add."""
    names = {expert.id: expert.name for expert in experts}
    session = GroupVoiceSession(panel_id="panel", member_ids=set(names), member_names=names)
    winner = await session.decide_raise_hands(utterance, raise_hand_prompt=raise_prompt)
    hands = set(session.hands)
    chosen = set(hands)
    if winner is not None:
        chosen.add(winner)
    speakers = [expert for expert in experts if expert.id in chosen]
    return speakers, hands, session


def _message_out(row: SmePanelMessage, persona_name: str | None) -> SmeMessageOut:
    return SmeMessageOut(
        id=row.id,
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        created_at=row.created_at,
        persona_id=row.persona_id,
        persona_name=persona_name,
    )


async def run_panel_message(  # noqa: PLR0915
    session_factory: async_sessionmaker[AsyncSession],
    *,
    panel_id: int,
    customer_id: int,
    user: UserAccount,
    message: str,
    workspace_id: str | None = None,
    mentions: list[DocumentMention] | None = None,
) -> list[SmeMessageOut]:
    text = message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")

    token = uuid4().hex
    async with session_factory() as session:
        await _require_panel(session, panel_id, customer_id)
        await session.commit()
    fence = await acquire_panel_lease(session_factory, panel_id, token=token)
    heartbeat = PanelLeaseHeartbeat(session_factory, panel_id, token=token, fence=fence).start()
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
            lines = [(row.role, row.persona_id, row.content) for row in previous]
            prompts = await require_prompts_for_persona(session, experts[0])
            raise_prompt = prompt_template(prompts, "sme.group_voice.raise_hand")
            await session.commit()
        await publish_document_open(
            session_factory,
            customer_id=customer_id,
            user_id=user.id,
            panel_id=panel_id,
            workspace_id=workspace_id,
            message=text,
            history=[(role, content, None) for role, _speaker, content in lines],
        )
        opened = await load_open_workspace(
            session_factory,
            workspace_id=workspace_id,
            user_id=user.id,
            customer_id=customer_id,
            mentions=mentions,
        )
        state = None if opened is None else opened[0]
        experts, _hands, voice_session = await speakers_for_utterance(experts, text, raise_prompt)
        sent: set[tuple[str, ...]] = set()

        async def one_reply(expert: Persona) -> str:
            async def emit_tools(calls: list[dict]) -> None:
                await publish_speaker_tools(
                    customer_id=customer_id,
                    user_id=user.id,
                    panel_id=panel_id,
                    calls=calls,
                    sent=sent,
                    expert_id=expert.id,
                )

            return await expert_group_reply(
                session_factory,
                customer_id=customer_id,
                user_id=user.id,
                persona_id=expert.id,
                user_text=text,
                context=(
                    workspace_id,
                    state,
                    group_history(voice_session, expert.id, lines),
                    speaker_note(voice_session, expert.id),
                ),
                on_client_tools=emit_tools,
            )

        replies = await asyncio.gather(*[one_reply(expert) for expert in experts])
        if heartbeat.lost.is_set():
            raise HTTPException(status_code=409, detail="stale_panel_turn")

        async with session_factory() as session:
            if not await panel_lease_still_held(session, panel_id, token=token, fence=fence):
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
                if not reply:
                    continue
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
            await session.commit()
        return [_message_out(row, name) for row, name in created]
    finally:
        await heartbeat.aclose()
        async with session_factory() as session:
            await release_panel_lease(session, panel_id, token=token, fence=fence)
            await session.commit()
