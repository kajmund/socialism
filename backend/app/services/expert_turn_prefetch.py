"""Run expert memory search beside the turn's Jev routing.

The caller commits first. Neither call holds a database connection.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from app.database.models import Persona
from app.services import expert_reasoning_turn
from app.services.expert_async_tools import LibraryToolScope
from app.services.expert_memory_context import expert_memory_context
from app.services.persona_chat_turn_support import append_configured_system_prompt


@dataclass(frozen=True)
class TurnPrompt:
    workspace_extra: str
    extra_system_prompt_key: str | None
    group_note: str | None
    prompt_key: str | None
    image_sha256: str | None


async def profile_with_memory(
    persona: Persona,
    message: str,
    prompts: dict[str, str],
    scope: LibraryToolScope,
    *,
    tools: tuple[list[str], list[dict[str, Any]]],
    prompt: TurnPrompt,
) -> tuple[Any, str]:
    memory_task = asyncio.create_task(
        expert_memory_context(
            persona, message, prompts, image_sha256=prompt.image_sha256,
        )
    )
    try:
        profile = await expert_reasoning_turn.route_expert_turn(
            scope, prompts, persona.kind, tools, prompt_key=prompt.prompt_key,
        )
        remembered = await memory_task
    except BaseException:
        memory_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await memory_task
        raise
    return profile, _compose_memory(remembered, prompts, prompt)


def _compose_memory(remembered: str, prompts: dict[str, str], prompt: TurnPrompt) -> str:
    context = remembered
    if prompt.workspace_extra:
        context = (
            f"{context}\n\n{prompt.workspace_extra}".strip()
            if context
            else prompt.workspace_extra
        )
    return append_configured_system_prompt(
        context, prompts, prompt.extra_system_prompt_key, prompt.group_note,
    )
