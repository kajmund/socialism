import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona, UserAccount
from app.services.actor_profiles import (
    ACTOR_TOOL_IDS,
    ActorProfileTools,
    actor_tool_specs,
)
from app.services.dd.company_mcp import (
    COMPANY_TOOL_NAMES,
    RESEARCH_TOOL_NAME,
    company_tool_specs,
    research_tool_spec,
    run_company_tool,
)
from app.services.expert_chat_research_tool import research_tool_handler_for_chat
from app.services.expert_tools import filter_openai_tools, resolve_expert_tools
from app.services.oasis_agent_tools import (
    SEARCH_TOOL_NAMES,
    run_search_tool,
    search_tool_specs,
)


def live_voice_tool_specs(persona: Persona) -> list[dict[str, Any]]:
    allowed = frozenset(resolve_expert_tools(persona.tools))
    specs = [
        *company_tool_specs(),
        *search_tool_specs(),
        research_tool_spec(),
        *actor_tool_specs(),
    ]
    return filter_openai_tools(specs, allowed)


async def run_live_voice_tool(
    session: AsyncSession,
    *,
    persona: Persona,
    user: UserAccount,
    session_id: str,
    name: str,
    arguments: dict[str, Any],
    history: list[tuple[str, str, str | None]],
    user_message: str,
) -> str:
    allowed = frozenset(resolve_expert_tools(persona.tools))
    if name not in allowed:
        raise ValueError("voice_tool_not_allowed")
    if name in COMPANY_TOOL_NAMES:
        return await run_company_tool(name, arguments)
    if name in SEARCH_TOOL_NAMES:
        return await asyncio.to_thread(run_search_tool, name, arguments)
    if name in ACTOR_TOOL_IDS:
        return await ActorProfileTools(
            session,
            user_id=user.id,
            customer_id=persona.customer_id,
            conversation=f"expert:{persona.id}:voice:{session_id}",
        )(name, arguments)
    if name == RESEARCH_TOOL_NAME:
        handler = research_tool_handler_for_chat(
            session,
            persona=persona,
            history=history,
            user_message=user_message,
        )
        return await handler(arguments)
    raise ValueError("unknown_voice_tool")
