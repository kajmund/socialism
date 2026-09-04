"""Panel catalog CRUD — module-scoped sub-questions and expert profiles."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.auth.scope import customer_id_for_user
from app.database.models import PanelExpertProfile, PanelSubQuestion, UserAccount
from app.database.session import get_session
from app.modules.registry import MODULE_REGISTRY
from app.services.dd.expert_keys import expert_role_key
from app.services.panel.catalog_schemas import (
    PanelExpertProfileCreate,
    PanelExpertProfileOut,
    PanelExpertProfileUpdate,
    PanelSubQuestionCreate,
    PanelSubQuestionOut,
    PanelSubQuestionUpdate,
)
from app.services.panel.expert_profiles_store import (
    create_expert_profile,
    get_expert_profile,
    get_expert_profiles,
    next_expert_profile_sort_order,
    update_expert_profile,
)
from app.services.panel.sub_questions_store import (
    create_sub_question,
    delete_sub_question,
    get_sub_question,
    get_sub_questions,
    next_sub_question_sort_order,
    sub_question_key_in_use,
    update_sub_question,
)

router = APIRouter(
    prefix="/panel",
    tags=["panel-catalog"],
    dependencies=[Depends(require_admin)],
)

_SORT_ORDER_CONFLICT = "Sort order already used for this module"
_SUB_QUESTION_KEY_CONFLICT = "Sub-question key already exists for this module"
_EXPERT_KEY_CONFLICT = "Expert profile key already exists"


def _conflict_from_integrity(exc: IntegrityError, *, key_detail: str) -> HTTPException:
    raw = str(exc.orig if exc.orig is not None else exc).lower()
    detail = _SORT_ORDER_CONFLICT if "sort_order" in raw else key_detail
    return HTTPException(status_code=409, detail=detail)


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _require_module(module: str) -> None:
    if module not in MODULE_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown module {module!r}")


def _serialize_sub_question(row: PanelSubQuestion) -> PanelSubQuestionOut:
    return PanelSubQuestionOut(
        id=row.id,
        module=row.module,
        key=row.key,
        label=row.label,
        sort_order=row.sort_order,
        active=row.active,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
    )


def _serialize_expert_profile(
    row: PanelExpertProfile, *, viewed_module: str | None = None
) -> PanelExpertProfileOut:
    modules = [str(item) for item in (row.modules or [])]
    module = viewed_module if viewed_module is not None else (modules[0] if modules else "")
    return PanelExpertProfileOut(
        id=row.id,
        module=module,
        modules=modules,
        key=row.key,
        name=row.name,
        description=row.description,
        kompetensomrade=row.kompetensomrade,
        radgivningsstil=row.radgivningsstil,
        yrkesbakgrund=row.yrkesbakgrund,
        professionell_anekdot=row.professionell_anekdot,
        sort_order=row.sort_order,
        active=row.active,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
    )


@router.get("/sub-questions", response_model=list[PanelSubQuestionOut])
async def list_sub_questions(
    module: str = Query(min_length=1, max_length=32),
    include_inactive: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> list[PanelSubQuestionOut]:
    _require_module(module)
    rows = await get_sub_questions(session, module, active_only=not include_inactive)
    return [_serialize_sub_question(row) for row in rows]


@router.post("/sub-questions", response_model=PanelSubQuestionOut, status_code=201)
async def post_sub_question(
    body: PanelSubQuestionCreate,
    session: AsyncSession = Depends(get_session),
) -> PanelSubQuestionOut:
    _require_module(body.module)
    sort_order = body.sort_order
    if sort_order is None:
        sort_order = await next_sub_question_sort_order(session, body.module)
    try:
        row = await create_sub_question(
            session,
            module=body.module,
            key=body.key,
            label=body.label,
            sort_order=sort_order,
            active=body.active,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict_from_integrity(exc, key_detail=_SUB_QUESTION_KEY_CONFLICT) from exc
    return _serialize_sub_question(row)


@router.patch("/sub-questions/{row_id}", response_model=PanelSubQuestionOut)
async def patch_sub_question(
    row_id: int,
    body: PanelSubQuestionUpdate,
    session: AsyncSession = Depends(get_session),
) -> PanelSubQuestionOut:
    row = await get_sub_question(session, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Sub-question not found")
    if body.label is None and body.sort_order is None and body.active is None:
        raise HTTPException(status_code=400, detail="PATCH body is empty")
    try:
        row = await update_sub_question(
            session,
            row,
            label=body.label,
            sort_order=body.sort_order,
            active=body.active,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict_from_integrity(exc, key_detail=_SUB_QUESTION_KEY_CONFLICT) from exc
    return _serialize_sub_question(row)


@router.delete("/sub-questions/{row_id}", status_code=204)
async def remove_sub_question(
    row_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await get_sub_question(session, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Sub-question not found")
    if await sub_question_key_in_use(session, row.key):
        raise HTTPException(
            status_code=409,
            detail="Sub-question is used in a run or report; delete those first",
        )
    await delete_sub_question(session, row)
    await session.commit()


@router.get("/expert-profiles", response_model=list[PanelExpertProfileOut])
async def list_expert_profiles(
    module: str = Query(min_length=1, max_length=32),
    include_inactive: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(require_admin),
) -> list[PanelExpertProfileOut]:
    _require_module(module)
    customer_id = await customer_id_for_user(session, user)
    rows = await get_expert_profiles(
        session, module, customer_id=customer_id, active_only=not include_inactive
    )
    return [_serialize_expert_profile(row, viewed_module=module) for row in rows]


@router.post("/expert-profiles", response_model=PanelExpertProfileOut, status_code=201)
async def post_expert_profile(
    body: PanelExpertProfileCreate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(require_admin),
) -> PanelExpertProfileOut:
    _require_module(body.module)
    customer_id = await customer_id_for_user(session, user)
    key = body.key or expert_role_key(body.name)
    sort_order = body.sort_order
    if sort_order is None:
        sort_order = await next_expert_profile_sort_order(
            session, customer_id=customer_id
        )
    try:
        row = await create_expert_profile(
            session,
            customer_id=customer_id,
            module=body.module,
            key=key,
            name=body.name,
            description=body.description,
            kompetensomrade=body.kompetensomrade,
            radgivningsstil=body.radgivningsstil,
            yrkesbakgrund=body.yrkesbakgrund,
            professionell_anekdot=body.professionell_anekdot,
            sort_order=sort_order,
            active=body.active,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict_from_integrity(exc, key_detail=_EXPERT_KEY_CONFLICT) from exc
    return _serialize_expert_profile(row, viewed_module=body.module)


@router.patch("/expert-profiles/{row_id}", response_model=PanelExpertProfileOut)
async def patch_expert_profile(
    row_id: int,
    body: PanelExpertProfileUpdate,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(require_admin),
) -> PanelExpertProfileOut:
    customer_id = await customer_id_for_user(session, user)
    row = await get_expert_profile(session, row_id)
    if row is None or row.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="Expert profile not found")
    if body.model_dump(exclude_unset=True) == {}:
        raise HTTPException(status_code=400, detail="PATCH body is empty")
    try:
        row = await update_expert_profile(
            session,
            row,
            name=body.name,
            description=body.description,
            kompetensomrade=body.kompetensomrade,
            radgivningsstil=body.radgivningsstil,
            yrkesbakgrund=body.yrkesbakgrund,
            professionell_anekdot=body.professionell_anekdot,
            sort_order=body.sort_order,
            active=body.active,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _conflict_from_integrity(exc, key_detail=_EXPERT_KEY_CONFLICT) from exc
    return _serialize_expert_profile(row)
