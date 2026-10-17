"""Reuse shared expert memory while keeping workspace documents private to their owner."""

from app.database.models import Persona
from app.services.expertgranskning.memory import get_expert_memory, memory_belongs_to
from app.services.expert_memory_context import (
    expert_memory_context,
    expert_memory_context_line,
)
from app.services.prompt_store import render_prompt
from app.services.workspace_memory_scope import WORKSPACE_MEMORY_SOURCE, workspace_memory_expert_id


async def workspace_memory_context(persona: Persona, query: str, prompts: dict[str, str], *,
                                   owner_id: str, workspace_parent_id: str) -> str:
    shared = await expert_memory_context(persona, query, prompts)
    private_key = workspace_memory_expert_id(persona, owner_id, workspace_parent_id=workspace_parent_id)
    private = await get_expert_memory().search(customer_id=persona.customer_id,
        expert_id=private_key, query=query,
        sources=frozenset({WORKSPACE_MEMORY_SOURCE}))
    private = [hit for hit in private if hit.source == WORKSPACE_MEMORY_SOURCE
               and memory_belongs_to(hit, customer_id=persona.customer_id, expert_id=private_key)]
    if not private:
        return shared
    lines = "\n".join(expert_memory_context_line(hit) for hit in private)
    if not shared:
        return render_prompt(prompts, "chat.expert.memory", memories=lines)
    return f"{shared.rstrip()}\n{lines}"
