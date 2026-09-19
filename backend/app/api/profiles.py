"""Authenticated profile photos and approval of exact expert-proposed edits."""

import asyncio
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import assert_kund_access
from app.database.models import ActorContextProposal, Kund, UserAccount
from app.database.session import get_session
from app.serializers import utcnow
from app.services.actor_profiles import serialize_proposal
from app.services.avatar_images import MAX_AVATAR_BYTES, normalize_avatar_image
from app.services.object_storage import (
    ObjectStorageError,
    delete_object,
    ensure_bucket,
    get_object,
    put_object,
)
from app.services.profiles import profile_values

router = APIRouter(tags=["profiles"])
AVATAR_BUCKET = "user-profiles"


async def _profile(
    session: AsyncSession, user: UserAccount, user_id: str, *, write: bool
) -> UserAccount:
    row = await session.get(UserAccount, user_id)
    if row is None:
        raise HTTPException(404, "profile_not_found")
    allowed = user.id == row.id or user.role == "admin"
    if not write and user.kund_id is not None and row.kund_id == user.kund_id:
        allowed = True
    if not allowed:
        raise HTTPException(403, "profile_access_denied")
    return row


@router.get("/profiles/{user_id}/avatar")
async def read_avatar(
    user_id: str,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    row = await _profile(session, user, user_id, write=False)
    if not row.avatar_key:
        raise HTTPException(404, "avatar_not_found")
    try:
        data, content_type = await get_object(AVATAR_BUCKET, row.avatar_key)
    except ObjectStorageError as exc:
        raise HTTPException(502, "avatar_storage_error") from exc
    return Response(
        data,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/profiles/{user_id}/avatar")
async def upload_avatar(
    user_id: str,
    file: UploadFile,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await _profile(session, user, user_id, write=True)
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(413, "avatar_too_large")
    data = await asyncio.to_thread(normalize_avatar_image, data)
    key = f"{uuid4().hex}.jpg"
    old = row.avatar_key
    try:
        await ensure_bucket(AVATAR_BUCKET)
        await put_object(AVATAR_BUCKET, key, data, "image/jpeg")
    except ObjectStorageError as exc:
        raise HTTPException(502, "avatar_storage_error") from exc
    result = await session.execute(
        update(UserAccount)
        .where(UserAccount.id == row.id, UserAccount.profile_revision == row.profile_revision)
        .values(avatar_key=key, profile_revision=UserAccount.profile_revision + 1)
    )
    if result.rowcount != 1:
        await session.rollback()
        await delete_object(AVATAR_BUCKET, key)
        raise HTTPException(409, "profile_changed")
    await session.commit()
    await session.refresh(row)
    if old:
        await delete_object(AVATAR_BUCKET, old)
    return profile_values(row)


@router.delete("/profiles/{user_id}/avatar")
async def remove_avatar(
    user_id: str,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await _profile(session, user, user_id, write=True)
    old = row.avatar_key
    result = await session.execute(
        update(UserAccount)
        .where(UserAccount.id == row.id, UserAccount.profile_revision == row.profile_revision)
        .values(avatar_key=None, profile_revision=UserAccount.profile_revision + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "profile_changed")
    await session.commit()
    await session.refresh(row)
    if old:
        await delete_object(AVATAR_BUCKET, old)
    return profile_values(row)


@router.get("/me/profile-proposals")
async def list_proposals(
    user: UserAccount = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[dict]:
    rows = await session.scalars(
        select(ActorContextProposal)
        .where(ActorContextProposal.user_id == user.id, ActorContextProposal.status == "pending")
        .order_by(ActorContextProposal.created_at)
    )
    return [
        serialize_proposal(row)
        for row in rows
        if user.role == "admin"
        or (
            row.target == "current_user"
            and (row.customer_id is None or row.customer_id == user.kund_id)
        )
    ]


class ProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation: str
    decision: Literal["approve", "reject"]


@router.post("/me/profile-proposals/{proposal_id}/decision")
async def decide_proposal(
    proposal_id: str,
    body: ProposalDecision,
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    proposal = await session.get(ActorContextProposal, proposal_id)
    if (
        proposal is None
        or proposal.user_id != user.id
        or proposal.conversation != body.conversation
    ):
        raise HTTPException(404, "proposal_not_found")
    if proposal.customer_id is not None:
        assert_kund_access(user, proposal.customer_id)
    if proposal.target == "customer" and user.role != "admin":
        raise HTTPException(403, "customer_edit_requires_admin")
    expected_status = "approved" if body.decision == "approve" else "rejected"
    if proposal.status != "pending":
        if proposal.status != expected_status:
            raise HTTPException(409, "proposal_already_decided")
        return serialize_proposal(proposal)
    claimed = await session.execute(
        update(ActorContextProposal)
        .where(ActorContextProposal.id == proposal.id, ActorContextProposal.status == "pending")
        .values(status=expected_status, decided_at=utcnow())
    )
    if claimed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "proposal_already_decided")
    if body.decision == "approve":
        model = Kund if proposal.target == "customer" else UserAccount
        target_id = proposal.customer_id if model is Kund else user.id
        result = await session.execute(
            update(model)
            .where(model.id == target_id, model.profile_revision == proposal.revision)
            .values(**proposal.changes, profile_revision=model.profile_revision + 1)
        )
        if result.rowcount != 1:
            await session.rollback()
            raise HTTPException(409, "profile_changed_create_new_proposal")
    await session.commit()
    await session.refresh(proposal)
    return serialize_proposal(proposal)
