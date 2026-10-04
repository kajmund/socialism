"""Short DB input phase, released external memory work, scoped legacy output."""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import assert_kund_access
from app.database.models import Persona, UserAccount
from app.schemas.domain import ExpertMemoryListOut, ExpertMemoryOut
from app.services.dd.expert_keys import persona_catalog_key
from app.services.expertgranskning.memory import ExpertMemoryHit, get_expert_memory, memory_belongs_to
from app.services.expertgranskning.memory_view import attach_expert_labels, directory_experts, expert_directory, serialize_memory_hit
from app.services.workspace_memory_scope import is_private_workspace_memory, workspace_memory_expert_id
from app.services.workspaces import list_workspaces, resolve_workspace


@dataclass(frozen=True)
class PersonaMemoryScope:
    customer_id: int
    owner_id: str
    workspace_id: str | None
    expert_id: str
    private_expert_ids: frozenset[str]
    is_expert: bool
    directory: dict


async def input_scope(session: AsyncSession, persona_id: str, user: UserAccount, *, expert_required: bool = True, workspace_id: str | None = None) -> PersonaMemoryScope:
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(404, "Persona not found")
    assert_kund_access(user, persona.customer_id)
    if expert_required and persona.kind != "expert":
        raise HTTPException(404, "Memory not found")
    parents = []
    if workspace_id is not None:
        parents = [await resolve_workspace(session, customer_id=persona.customer_id, user_id=user.id, workspace_id=workspace_id)]
    elif persona.kind == "expert":
        parents = await list_workspaces(session, customer_id=persona.customer_id, user_id=user.id)
    scope = PersonaMemoryScope(customer_id=persona.customer_id, owner_id=user.id, workspace_id=workspace_id,
        expert_id=persona_catalog_key(persona),
        private_expert_ids=frozenset(workspace_memory_expert_id(persona, user.id, workspace_parent_id=parent.id)
                                    for parent in parents), is_expert=persona.kind == "expert",
        directory=await expert_directory(session, customer_id=persona.customer_id) if persona.kind == "expert" else {})
    # The core workspace catalog may intentionally create the customer's
    # required company workspace. This request owns that input phase.
    await session.commit()
    return scope


async def list_memories(session: AsyncSession, persona_id: str, user: UserAccount, *, workspace_id: str | None = None) -> ExpertMemoryListOut:
    scope = await input_scope(session, persona_id, user, expert_required=False, workspace_id=workspace_id)
    if not scope.is_expert:
        return ExpertMemoryListOut(customer_id=scope.customer_id, count=0, memories=[])
    memory = get_expert_memory()
    hits = await memory.list_all(customer_id=scope.customer_id, expert_id=scope.expert_id)
    rows = attach_expert_labels(hits, scope.directory, customer_id=scope.customer_id)
    rows.extend(serialize_scoped_hit(hit, scope) for hit in await private_memories(scope))
    await revalidate_scope(session, scope)
    rows.sort(key=lambda row: (row.updated_at or row.created_at or "", row.id), reverse=True)
    return ExpertMemoryListOut(customer_id=scope.customer_id, count=len(rows), memories=rows,
                              experts=directory_experts(scope.directory, customer_id=scope.customer_id))


async def clear_memories(session: AsyncSession, persona_id: str, user: UserAccount, *, workspace_id: str | None = None) -> None:
    scope = await input_scope(session, persona_id, user, workspace_id=workspace_id)
    memory = get_expert_memory()
    public = await memory.list_all(customer_id=scope.customer_id, expert_id=scope.expert_id)
    hits = [hit for hit in public if not is_private_workspace_memory(hit)
            and memory_belongs_to(hit, customer_id=scope.customer_id, expert_id=scope.expert_id)]
    hits.extend(await private_memories(scope))
    await revalidate_scope(session, scope)
    for hit in hits:
        await revalidate_scope(session, scope)
        await memory.delete(memory_id=hit.id)


async def revalidate_scope(session: AsyncSession, scope: PersonaMemoryScope) -> None:
    if scope.workspace_id is None:
        return
    user = await session.get(UserAccount, scope.owner_id, populate_existing=True)
    if user is None:
        raise HTTPException(404, "Memory not found")
    await resolve_workspace(session, customer_id=scope.customer_id, user_id=user.id, workspace_id=scope.workspace_id)
    await session.rollback()


async def private_memories(scope: PersonaMemoryScope) -> list[ExpertMemoryHit]:
    memory = get_expert_memory()
    hits = []
    for expert_id in sorted(scope.private_expert_ids):
        rows = await memory.list_all(customer_id=scope.customer_id, expert_id=expert_id)
        hits.extend(hit for hit in rows if memory_belongs_to(hit, customer_id=scope.customer_id, expert_id=expert_id))
    return hits


def serialize_scoped_hit(hit: ExpertMemoryHit, scope: PersonaMemoryScope) -> ExpertMemoryOut:
    name, persona_id = scope.directory.get((scope.customer_id, scope.expert_id), ("", None))
    return serialize_memory_hit(hit, customer_id=scope.customer_id, expert_name=name, persona_id=persona_id)


async def require_scoped_hit(memory_id: str, scope: PersonaMemoryScope) -> ExpertMemoryHit:
    hit = await get_expert_memory().get(memory_id=memory_id)
    expert_id = scope.expert_id
    if hit and is_private_workspace_memory(hit):
        if hit.expert_id not in scope.private_expert_ids:
            raise HTTPException(404, "Memory not found")
        expert_id = hit.expert_id
    if hit is None or not memory_belongs_to(hit, customer_id=scope.customer_id, expert_id=expert_id):
        raise HTTPException(404, "Memory not found")
    return hit


async def update_memory(session: AsyncSession, persona_id: str, user: UserAccount, *, memory_id: str, text: str, workspace_id: str | None = None) -> ExpertMemoryOut:
    scope = await input_scope(session, persona_id, user, workspace_id=workspace_id)
    await require_scoped_hit(memory_id, scope)
    await revalidate_scope(session, scope)
    hit = await get_expert_memory().update(memory_id=memory_id, text=text)
    await revalidate_scope(session, scope)
    return serialize_scoped_hit(hit, scope)


async def delete_memory(session: AsyncSession, persona_id: str, user: UserAccount, *, memory_id: str, workspace_id: str | None = None) -> None:
    scope = await input_scope(session, persona_id, user, workspace_id=workspace_id)
    await require_scoped_hit(memory_id, scope)
    await revalidate_scope(session, scope)
    await get_expert_memory().delete(memory_id=memory_id)
