"""Owner namespace for private workspace memories; shared expert memory stays unchanged."""

from app.database.models import Persona
from app.services.dd.expert_keys import persona_catalog_key
from app.services.expertgranskning.memory import ExpertMemoryHit

WORKSPACE_MEMORY_SOURCE = "workspace_chat"
WORKSPACE_MEMORY_MARKER = ":workspace-owner:"


def workspace_memory_expert_id(persona: Persona, owner_id: str, *, workspace_parent_id: str) -> str:
    # A source label alone cannot prevent Mem0 from merging document facts
    # into an older memory under the same agent namespace.
    if not workspace_parent_id:
        raise ValueError("Private workspace memory requires its parent workspace")
    return f"{persona_catalog_key(persona)}{WORKSPACE_MEMORY_MARKER}{owner_id}:workspace:{workspace_parent_id}"


def is_private_workspace_memory(hit: ExpertMemoryHit) -> bool:
    return hit.source == WORKSPACE_MEMORY_SOURCE or WORKSPACE_MEMORY_MARKER in hit.expert_id
