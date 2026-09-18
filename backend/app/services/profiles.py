"""Shared profile serialization and explicit partial updates."""

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Kund, UserAccount
from app.schemas.profiles import ORGANIZATION_FIELDS, PROFILE_FIELDS


def profile_values(user: UserAccount) -> dict:
    return {
        **{k: getattr(user, k) for k in PROFILE_FIELDS},
        "avatar_url": f"/profiles/{user.id}/avatar?v={user.profile_revision}"
        if user.avatar_key
        else None,
        "profile_revision": user.profile_revision,
    }


def organization_values(kund: Kund) -> dict:
    return {k: getattr(kund, k) for k in ORGANIZATION_FIELDS}


def apply_fields(row: UserAccount | Kund, body: BaseModel, allowed: tuple[str, ...]) -> None:
    changes = body.model_dump(exclude_unset=True)
    changed = False
    for key in allowed:
        if key in changes:
            value = changes[key] or None
            if key == "country_code" and value:
                value = value.upper()
                if len(value) != 2 or not value.isascii() or not value.isalpha():
                    from fastapi import HTTPException

                    raise HTTPException(422, "invalid_country_code")
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed = True
    if changed:
        row.profile_revision = (row.profile_revision or 0) + 1


async def patch_fields(
    session: AsyncSession, row: UserAccount | Kund, body: BaseModel, allowed: tuple[str, ...]
) -> None:
    """Compare-and-swap so simultaneous form and expert edits cannot lose revisions."""
    from fastapi import HTTPException
    from sqlalchemy import update

    model = type(row)
    # Normalize on a transient instance to avoid ORM autoflush before the CAS.
    candidate = model(
        **{key: getattr(row, key) for key in allowed}, profile_revision=row.profile_revision
    )
    apply_fields(candidate, body, allowed)
    if candidate.profile_revision == row.profile_revision:
        return
    changes = {
        key: getattr(candidate, key)
        for key in allowed
        if getattr(candidate, key) != getattr(row, key)
    }
    result = await session.execute(
        update(model)
        .where(model.id == row.id, model.profile_revision == row.profile_revision)
        .values(**changes, profile_revision=model.profile_revision + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "profile_changed")
