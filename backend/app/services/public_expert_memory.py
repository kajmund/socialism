"""Legacy memory views never reveal or erase owner-private workspace namespaces."""

from fastapi import HTTPException

from app.services.expertgranskning.memory import ExpertMemoryHit, get_expert_memory, memory_belongs_to
from app.services.workspace_memory_scope import is_private_workspace_memory


async def require_public_memory(memory_id: str, *, customer_id: int | None = None,
                                expert_id: str | None = None) -> ExpertMemoryHit:
    hit = await get_expert_memory().get(memory_id=memory_id)
    if hit is None or is_private_workspace_memory(hit):
        raise HTTPException(404, "Memory not found")
    if customer_id is not None and not memory_belongs_to(hit, customer_id=customer_id, expert_id=expert_id):
        raise HTTPException(404, "Memory not found")
    return hit


async def clear_public_expert_memories(*, customer_id: int, expert_id: str | None = None) -> None:
    memory = get_expert_memory()
    hits = (await memory.list_all(customer_id=customer_id, expert_id=expert_id) if expert_id
            else await memory.list_for_customer(customer_id=customer_id))
    for hit in hits:
        if not is_private_workspace_memory(hit) and memory_belongs_to(hit, customer_id=customer_id, expert_id=expert_id):
            await memory.delete(memory_id=hit.id)
