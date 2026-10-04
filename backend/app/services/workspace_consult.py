"""Keep one-hop workspace consultation memories inside the owner's namespace."""

import asyncio

from app.database.models import Persona
from app.services.expertgranskning.memory import get_expert_memory
from app.services.workspace_memory_scope import WORKSPACE_MEMORY_SOURCE, workspace_memory_expert_id


async def remember_workspace_consult(asker: Persona, colleague: Persona, *, owner_id: str,
                                     workspace_parent_id: str, question: str, answer: str) -> None:
    memory = get_expert_memory()
    await asyncio.gather(*(
        memory.add_chat_turn(customer_id=expert.customer_id,
            expert_id=workspace_memory_expert_id(expert, owner_id, workspace_parent_id=workspace_parent_id),
            user_message=question, assistant_message=answer, source=WORKSPACE_MEMORY_SOURCE)
        for expert in (asker, colleague)
    ))
