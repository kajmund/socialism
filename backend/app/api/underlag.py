"""Personal underlag uploads — kund bucket, one owner path per user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.scope import customer_id_for_user
from app.database.models import StoredObject, UserAccount
from app.database.session import get_session
from app.modules.registry import MODULE_REGISTRY
from app.services.object_storage import KIND_UNDERLAG, MAX_UNDERLAG_BYTES, ObjectStorageError
from app.services.stored_objects import (
    create_underlag_folder,
    get_stored_object,
    get_underlag_folder,
    list_underlag,
    list_underlag_folders,
    own_underlag_folder,
    serialize_underlag,
    serialize_underlag_folder,
    upload_underlag,
)
from app.services.underlag_schemas import (
    UnderlagFolderCreate,
    UnderlagFolderOut,
    UnderlagListingOut,
    UnderlagOut,
)

router = APIRouter(prefix="/underlag", tags=["underlag"])


def _require_module(module: str) -> str:
    if module not in MODULE_REGISTRY:
        raise HTTPException(status_code=400, detail="unknown module")
    return module


def _own_underlag(row: StoredObject | None, *, customer_id: int, user_id: str) -> StoredObject:
    if (
        row is None
        or row.kind != KIND_UNDERLAG
        or row.customer_id != customer_id
        or row.owner_user_id != user_id
    ):
        raise HTTPException(status_code=404, detail="File not found")
    return row


@router.post("/folders", response_model=UnderlagFolderOut, status_code=201)
async def post_underlag_folder(
    body: UnderlagFolderCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> UnderlagFolderOut:
    module = _require_module(body.module)
    customer_id = await customer_id_for_user(session, user)
    try:
        row = await create_underlag_folder(
            session,
            customer_id=customer_id,
            owner_user_id=user.id,
            module=module,
            name=body.name,
            parent_id=body.parent_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return UnderlagFolderOut(**serialize_underlag_folder(row))


@router.get("", response_model=UnderlagListingOut)
async def get_underlag_list(
    module: str = Query(...),
    folder_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> UnderlagListingOut:
    module = _require_module(module)
    customer_id = await customer_id_for_user(session, user)
    if folder_id is not None:
        try:
            await own_underlag_folder(
                await get_underlag_folder(session, folder_id),
                customer_id=customer_id,
                owner_user_id=user.id,
                module=module,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    folders = await list_underlag_folders(
        session,
        customer_id=customer_id,
        owner_user_id=user.id,
        module=module,
        parent_id=folder_id,
    )
    rows = await list_underlag(
        session,
        customer_id=customer_id,
        owner_user_id=user.id,
        module=module,
        folder_id=folder_id,
    )
    return UnderlagListingOut(
        folder_id=folder_id,
        folders=[UnderlagFolderOut(**serialize_underlag_folder(folder)) for folder in folders],
        files=[UnderlagOut(**serialize_underlag(row, include_text=False)) for row in rows],
    )


@router.post("", response_model=UnderlagOut, status_code=201)
async def post_underlag(
    module: str = Query(...),
    folder_id: str | None = Query(None),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> UnderlagOut:
    module = _require_module(module)
    customer_id = await customer_id_for_user(session, user)
    raw = await file.read(MAX_UNDERLAG_BYTES + 1)
    try:
        row = await upload_underlag(
            session,
            customer_id=customer_id,
            owner_user_id=user.id,
            module=module,
            filename=file.filename or "file",
            content_type=file.content_type or "application/octet-stream",
            data=raw,
            folder_id=folder_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ObjectStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await session.commit()
    return UnderlagOut(**serialize_underlag(row, include_text=True))


@router.get("/{object_id}", response_model=UnderlagOut)
async def get_underlag(
    object_id: str,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> UnderlagOut:
    customer_id = await customer_id_for_user(session, user)
    row = _own_underlag(
        await get_stored_object(session, object_id),
        customer_id=customer_id,
        user_id=user.id,
    )
    return UnderlagOut(**serialize_underlag(row, include_text=True))
