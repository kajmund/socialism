"""Admin endpoints for inspecting expert long-term memory."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.auth.scope import effective_customer_id
from app.database.models import Kund, UserAccount
from app.database.session import get_session
from app.schemas.domain import (
    ExpertMemoryExpertOut,
    ExpertMemoryListOut,
    ExpertMemoryOut,
    ExpertMemoryUpdate,
)
from app.services.expertgranskning.memory import (
    ExpertMemoryHit,
    customer_id_from_memory_user,
    get_expert_memory,
)
from app.services.expertgranskning.memory_view import (
    attach_expert_labels,
    directory_experts,
    expert_directory,
    labeled_memory,
    serialize_memory_hit,
)

router = APIRouter(
    prefix="/expert-memory",
    tags=["expert-memory"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=ExpertMemoryListOut)
async def list_expert_memories(
    customer_id: int | None = Query(default=None),
    expert_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(require_admin),
) -> ExpertMemoryListOut:
    scoped = effective_customer_id(user, customer_id)
    cleaned_expert = (expert_id or "").strip()
    if scoped is not None:
        memories, experts = await _memories_for_customer(
            session, scoped, expert_id=cleaned_expert or None
        )
        return ExpertMemoryListOut(
            customer_id=scoped,
            count=len(memories),
            memories=memories,
            experts=experts,
        )

    kund_ids = list((await session.execute(select(Kund.id).order_by(Kund.id))).scalars())
    memories: list[ExpertMemoryOut] = []
    experts: list[ExpertMemoryExpertOut] = []
    for kund_id in kund_ids:
        kund_memories, kund_experts = await _memories_for_customer(
            session, kund_id, expert_id=cleaned_expert or None
        )
        memories.extend(kund_memories)
        experts.extend(kund_experts)
    memories.sort(
        key=lambda row: (row.updated_at or row.created_at or "", row.id),
        reverse=True,
    )
    experts.sort(key=lambda row: (row.name, row.expert_id, row.customer_id))
    return ExpertMemoryListOut(
        customer_id=None,
        count=len(memories),
        memories=memories,
        experts=experts,
    )


@router.delete("", status_code=204)
async def clear_expert_memories(
    customer_id: int | None = Query(default=None),
    expert_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(require_admin),
) -> Response:
    scoped = effective_customer_id(user, customer_id)
    cleaned_expert = (expert_id or "").strip() or None
    memory = get_expert_memory()
    if scoped is not None:
        await memory.delete_all(customer_id=scoped, expert_id=cleaned_expert)
        return Response(status_code=204)
    kund_ids = list((await session.execute(select(Kund.id).order_by(Kund.id))).scalars())
    for kund_id in kund_ids:
        await memory.delete_all(customer_id=kund_id, expert_id=cleaned_expert)
    return Response(status_code=204)


@router.patch("/{memory_id}", response_model=ExpertMemoryOut)
async def update_expert_memory(
    memory_id: str,
    body: ExpertMemoryUpdate,
    session: AsyncSession = Depends(get_session),
    _user: UserAccount = Depends(require_admin),
) -> ExpertMemoryOut:
    memory = get_expert_memory()
    existing = await memory.get(memory_id=memory_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    updated = await memory.update(memory_id=memory_id, text=body.text)
    customer_id = customer_id_from_memory_user(updated.user_id or existing.user_id)
    if customer_id is None:
        return serialize_memory_hit(updated)
    return await labeled_memory(session, updated, customer_id=customer_id)


@router.delete("/{memory_id}", status_code=204)
async def delete_expert_memory(
    memory_id: str,
    _user: UserAccount = Depends(require_admin),
) -> Response:
    memory = get_expert_memory()
    existing = await memory.get(memory_id=memory_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    await memory.delete(memory_id=memory_id)
    return Response(status_code=204)


async def _memories_for_customer(
    session: AsyncSession,
    customer_id: int,
    *,
    expert_id: str | None,
) -> tuple[list[ExpertMemoryOut], list[ExpertMemoryExpertOut]]:
    memory = get_expert_memory()
    hits: list[ExpertMemoryHit]
    if expert_id:
        hits = await memory.list_all(customer_id=customer_id, expert_id=expert_id)
    else:
        hits = await memory.list_for_customer(customer_id=customer_id)
    directory = await expert_directory(session, customer_id=customer_id)
    return (
        attach_expert_labels(hits, directory, customer_id=customer_id),
        directory_experts(directory, customer_id=customer_id),
    )
