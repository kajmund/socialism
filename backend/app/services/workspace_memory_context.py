"""Reuse shared expert memory while keeping workspace documents private to their owner."""

from app.database.models import Persona
from app.services.expertgranskning.memory import get_expert_memory, memory_belongs_to
from app.services.persona_chat import expert_memory_context
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
    context = render_prompt(prompts, "chat.expert.memory", memories="\n".join(f"- {hit.text}" for hit in private))
    return "\n".join(part for part in (shared, context) if part)
