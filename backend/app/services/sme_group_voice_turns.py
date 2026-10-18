"""Automatic expert turns for SME group voice.

When the floor is granted, admit a real expert turn, run it, and speak the result.
The expert hears the panel transcript, not their private chat.
"""

from __future__ import annotations

import logging
import re
from uuid import uuid4

from sqlalchemy import select

from app.database.models import SmePanelMessage
from app.serializers import utcnow
from app.services import jobs as jobs_service
from app.services.sme_expert_turns import accept_expert_turn, execute_expert_turn
from app.services.sme_group_voice import GroupVoiceSession, raised_hand_line
from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime
from app.services.sme_open_document import load_open_workspace
from app.services.speech_segmenter import strip_voice_tags

logger = logging.getLogger(__name__)

_LOOSE_TAG = re.compile(r"\[([a-z ]+)\]", re.IGNORECASE)
_REPEATED_SPACE = re.compile(r"[ \t]{2,}")


def plain_group_reply(reply: str) -> str:
    """Drop voice-control tags, including invented ones like [happy], from the group reply."""
    text = _LOOSE_TAG.sub("", strip_voice_tags(reply))
    return _REPEATED_SPACE.sub(" ", text).strip()


PanelLine = tuple[str, str | None, str]
HistoryTurn = tuple[str, str, str | None, str | None]


def _panel_instruction(session: GroupVoiceSession) -> str:
    names = ", ".join(name for name in session.member_names.values() if name)
    return (
        f"Du sitter i en expertpanel med {names}. "
        "Du hör de andras inlägg och svarar som dig själv i gruppen. "
        "Fortsätt inte ett privat samtal. "
        "Upprepa inte en genomgång som redan har getts."
    )


def _with_hand(session: GroupVoiceSession, persona_id: str, note: str) -> str:
    others = [
        session.member_names.get(member_id, member_id)
        for member_id in sorted(session.hands)
        if member_id != persona_id
    ]
    return f"{note} {raised_hand_line(others)}"


def group_note(session: GroupVoiceSession) -> str:
    note = _panel_instruction(session)
    if session.floor_reason != "hand" or session.floor is None:
        return note
    return _with_hand(session, session.floor, note)


def speaker_note(session: GroupVoiceSession, persona_id: str) -> str:
    """Same panel instruction as live voice. A raised hand adds the same line."""
    note = _panel_instruction(session)
    if persona_id not in session.hands:
        return note
    return _with_hand(session, persona_id, note)


def group_history(session: GroupVoiceSession, persona_id: str, lines: list[PanelLine]) -> list[HistoryTurn]:
    history: list[HistoryTurn] = []
    for role, speaker_id, content in lines:
        if role == "assistant" and speaker_id == persona_id:
            history.append(("assistant", content, None, None))
            continue
        if role == "assistant":
            name = session.member_names.get(speaker_id or "", "Expert")
            history.append(("user", f"{name}: {content}", None, None))
            continue
        history.append(("user", content, None, None))
    return history


async def run_floor_turn(
    *,
    session: GroupVoiceSession,
    runtime: GroupVoiceAudioRuntime,
    user_text: str,
    user_id: str,
    customer_id: int,
    workspace_id: str | None = None,
) -> None:
    """If an expert holds the floor, generate their reply and speak it."""
    persona_id = session.floor
    if not persona_id or not user_text.strip():
        return
    factory = jobs_service.job_session_factory()
    spoke = False
    try:
        lines = await _panel_lines(factory, int(session.panel_id))
        opened = await load_open_workspace(
            factory,
            workspace_id=workspace_id,
            user_id=user_id,
            customer_id=customer_id,
            expert_id=persona_id,
        )
        state = None if opened is None else opened[0]

        async def emit_tools(calls: list[dict], *, turn_id: str) -> None:
            await runtime.emit_workspace_tool(
                calls, expert_id=persona_id, turn_id=turn_id,
            )

        reply = await expert_group_reply(
            factory,
            customer_id=customer_id,
            user_id=user_id,
            persona_id=persona_id,
            user_text=user_text,
            context=(
                workspace_id,
                state,
                group_history(session, persona_id, lines),
                group_note(session),
            ),
            on_client_tools=emit_tools,
        )
        if reply:
            await _store_exchange(
                factory,
                customer_id=customer_id,
                panel_id=int(session.panel_id),
                persona_id=persona_id,
                user_text=user_text,
                reply=reply,
            )
        if reply and session.floor == persona_id:
            spoke = True
            await runtime.speak_as(persona_id, reply)
    except Exception:
        logger.exception("group voice expert turn failed for %s", persona_id)
    finally:
        if not spoke and session.floor == persona_id:
            await runtime.release_unspoken(persona_id)


async def _panel_lines(factory, panel_id: int) -> list[PanelLine]:
    async with factory() as db:
        result = await db.execute(
            select(SmePanelMessage)
            .where(SmePanelMessage.population_id == panel_id)
            .order_by(SmePanelMessage.id.asc())
        )
        return [(row.role, row.persona_id, row.content) for row in result.scalars().all()]


async def expert_group_reply(
    factory,
    *,
    customer_id: int,
    user_id: str,
    persona_id: str,
    user_text: str,
    context: tuple,
    on_client_tools,
) -> str:
    """One expert reply, the same turn live voice uses."""
    workspace_id, state, history, note = context
    request_id = f"group-voice-{uuid4().hex}"

    async def deliver_tools(calls: list[dict]) -> None:
        await on_client_tools(calls, turn_id=request_id)

    accepted = await _accept(
        factory,
        request_id=request_id,
        customer_id=customer_id,
        user_id=user_id,
        persona_id=persona_id,
        user_text=user_text,
    )
    if accepted is None:
        return ""
    token, fence = accepted
    done = await execute_expert_turn(
        factory,
        request_id=request_id,
        persona_id=persona_id,
        message=user_text,
        image_sha256=None,
        fence=fence,
        token=token,
        on_token=None,
        workspace_id=None if state is None else workspace_id,
        workspace_state=state,
        on_client_tools=deliver_tools,
        group_history=history,
        group_note=note,
    )
    return plain_group_reply(done.reply or "")


async def _accept(factory, *, request_id, customer_id, user_id, persona_id, user_text):
    async with factory() as db:
        turn, should_run = await accept_expert_turn(
            db,
            request_id=request_id,
            customer_id=customer_id,
            user_id=user_id,
            persona_id=persona_id,
            message=user_text,
            image_sha256=None,
        )
        await db.commit()
        if not should_run:
            return None
        return turn.lease_token or "", turn.fence


async def _store_exchange(
    factory,
    *,
    customer_id: int,
    panel_id: int,
    persona_id: str,
    user_text: str,
    reply: str,
) -> None:
    async with factory() as db:
        db.add(
            SmePanelMessage(
                customer_id=customer_id,
                population_id=panel_id,
                role="user",
                content=user_text,
                created_at=utcnow(),
            )
        )
        db.add(
            SmePanelMessage(
                customer_id=customer_id,
                population_id=panel_id,
                role="assistant",
                persona_id=persona_id,
                content=reply,
                created_at=utcnow(),
            )
        )
        await db.commit()
