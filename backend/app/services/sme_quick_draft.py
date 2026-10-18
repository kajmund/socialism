"""Fast-model quick messages in the SME chat: acknowledgment and progress.

The acknowledgment ("ok, jag kollar…") is generated before the full reply
starts, inserted into the conversation as a line the expert has already said,
and sent to the user. If the full reply is late, a progress line ("…jag
arbetar fortfarande med avtalet, snart klar…") is generated from the user's
question. Neither message answers the question and neither is persisted.

Loads the expert prompt and recent history in one short transaction and closes
it before any LLM call. No user or assistant message is written.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import APITimeoutError, OpenAIError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database.models import Persona, PersonaMessage
from app.llm import stream_text
from app.llm.chat import expert_block
from app.schemas.domain import EXPERT_CHAT_MODE
from app.serializers import profile_from_dict
from app.services.expert_reasoning import bound_expert_profile
from app.services.persona_chat import library_chat_filter
from app.services.prompt_render import prompt_template
from app.services.prompt_store import require_prompts_for_persona

logger = logging.getLogger(__name__)

QUICK_DRAFT_PROMPT_KEY = "chat.expert.quick_draft"
QUICK_PROGRESS_PROMPT_KEY = "chat.expert.quick_progress"
# Expected failure modes only: DB load, missing prompt, provider/timeout errors.
_QUICK_ERRORS = (
    SQLAlchemyError,
    RuntimeError,
    TimeoutError,
    APITimeoutError,
    OpenAIError,
    ValueError,
)


async def complete_quick_draft(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    persona_id: str,
    message: str,
) -> str | None:
    """Generate the full acknowledgment text, or None when it cannot be written."""
    return await _complete_quick_message(
        session_factory,
        persona_id=persona_id,
        message=message,
        prompt_key=QUICK_DRAFT_PROMPT_KEY,
        said=None,
    )


async def complete_quick_progress(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    persona_id: str,
    message: str,
    said: str | None,
) -> str | None:
    """Generate a progress line for a late full reply, or None on failure."""
    return await _complete_quick_message(
        session_factory,
        persona_id=persona_id,
        message=message,
        prompt_key=QUICK_PROGRESS_PROMPT_KEY,
        said=said,
    )


async def _complete_quick_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    persona_id: str,
    message: str,
    prompt_key: str,
    said: str | None,
) -> str | None:
    parts: list[str] = []
    async for chunk in stream_quick_message(
        session_factory,
        persona_id=persona_id,
        message=message,
        prompt_key=prompt_key,
        said=said,
    ):
        parts.append(chunk)
    text = "".join(parts).strip()
    return text or None


def stream_quick_draft(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    persona_id: str,
    message: str,
) -> AsyncIterator[str]:
    """Yield the acknowledgment stream; see ``stream_quick_message``."""
    return stream_quick_message(
        session_factory,
        persona_id=persona_id,
        message=message,
        prompt_key=QUICK_DRAFT_PROMPT_KEY,
        said=None,
    )


async def stream_quick_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    persona_id: str,
    message: str,
    prompt_key: str,
    said: str | None,
) -> AsyncIterator[str]:
    """Yield a short fast-model chat line, never an answer.

    Stops quietly on any failure (timeout, provider error, missing prompt):
    the quick line is best-effort and the full reply always follows.
    Cancellation propagates so the caller can stop the stream.
    """
    try:
        async with session_factory() as session:
            persona = await session.get(Persona, persona_id)
            if persona is None:
                return
            profile = profile_from_dict(persona.profile, persona.name)
            prompts = await require_prompts_for_persona(session, persona)
            rules = prompt_template(prompts, prompt_key)
            result = await session.execute(
                select(PersonaMessage)
                .where(*library_chat_filter(persona_id, EXPERT_CHAT_MODE))
                .order_by(PersonaMessage.id.asc())
            )
            history = [(row.role, row.content) for row in result.scalars().all()]
            # Purpose-built system message: the quick line must not inherit the
            # chat mode's "analysera och svara" instructions, or the model answers
            # the question instead of just acknowledging progress.
            system = (
                f"Profil för {profile.name} — du är den här experten:\n"
                f"{expert_block(profile)}\n\n"
                f"{rules}"
            )
            messages = [{"role": "system", "content": system}]
            messages.extend(
                {"role": role, "content": content} for role, content in history
            )
            messages.append({"role": "user", "content": message})
            if said:
                messages.append({"role": "assistant", "content": said})
            await session.commit()
    except asyncio.CancelledError:
        raise
    except _QUICK_ERRORS as exc:
        logger.info("sme.quick_message_failed persona_id=%s error=%s", persona_id, exc)
        return

    try:
        async for chunk in _stream_bounded(messages, prompt_key=prompt_key):
            yield chunk
    except asyncio.CancelledError:
        raise
    except _QUICK_ERRORS as exc:
        logger.info("sme.quick_message_failed persona_id=%s error=%s", persona_id, exc)
        return


async def _stream_bounded(
    messages: list[dict[str, Any]],
    *,
    prompt_key: str,
) -> AsyncIterator[str]:
    budget = settings.sme_quick_draft_max_chars
    written = 0
    with bound_expert_profile("fast"):
        stream = stream_text(messages, prompt_key=prompt_key)
        try:
            async with asyncio.timeout(settings.sme_quick_draft_timeout_seconds):
                async for chunk in stream:
                    if not chunk:
                        continue
                    written += len(chunk)
                    yield chunk
                    if written >= budget:
                        break
        finally:
            await stream.aclose()
