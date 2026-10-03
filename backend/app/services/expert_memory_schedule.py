"""Write expert memory after a chat turn has already been returned."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from app.database.models import Persona
from app.services.dd.expert_keys import persona_catalog_key
from app.services.expertgranskning.memory import get_expert_memory

logger = logging.getLogger(__name__)
memory_tasks: set[asyncio.Task[None]] = set()


def schedule_expert_memory_update(
    persona: Persona,
    *,
    message: str,
    reply: str,
    image_sha256: str | None,
    source: Literal["persona_chat", "panel_chat", "expert_consult"] = "persona_chat",
    session_id: str | None = None,
) -> None:
    """Write expert memory after the turn has returned. Failures stay in the log."""
    if persona.kind != "expert":
        return
    customer_id = persona.customer_id
    expert_id = persona_catalog_key(persona)
    task = asyncio.create_task(
        _update_expert_memory(
            customer_id=customer_id,
            expert_id=expert_id,
            message=message,
            reply=reply,
            image_sha256=image_sha256,
            source=source,
            session_id=session_id,
        ),
        name=f"expert-memory:{persona.id}",
    )
    memory_tasks.add(task)
    task.add_done_callback(memory_tasks.discard)


async def _update_expert_memory(
    *,
    customer_id: int,
    expert_id: str,
    message: str,
    reply: str,
    image_sha256: str | None,
    source: str,
    session_id: str | None,
) -> None:
    try:
        await get_expert_memory().add_chat_turn(
            customer_id=customer_id,
            expert_id=expert_id,
            user_message=message,
            assistant_message=reply,
            source=source,
            image_sha256=image_sha256,
            session_id=session_id,
        )
    except Exception:
        logger.exception("Expert memory update failed")
