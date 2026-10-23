"""Opt-in admin API for the clause SSR library. Isolated from research/SWE."""

from __future__ import annotations

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import require_admin
from app.database.models import UserAccount
from app.services.knowledge.scope import KnowledgeTenantScope, customer_scope, shared_scope
from app.services.overgraph.catalogs import Catalog, get_runtime

from app.services.clause_ssr.anchors import list_anchors, promote_anchor
from app.services.clause_ssr.classifications import (
    get_classification,
    list_classifications,
    set_classification_active,
    upsert_classification,
)
from app.services.clause_ssr.match import match_query
from app.services.clause_ssr.queue import next_queue
from app.services.clause_ssr.select import build_anchor_set, list_anchor_sets
from app.services.clause_ssr.serialize import (
    anchor_json,
    classification_json,
    match_json,
    queue_json,
    session_json,
    set_json,
    verification_json,
)
from app.services.clause_ssr.sessions import apply_decision, get_or_create_session, undo_last
from app.services.clause_ssr.spec import catalog_embedding
from app.services.clause_ssr.types import ClassificationLevel, DecisionAnswer
from app.services.clause_ssr.verifications import record_decision

router = APIRouter(
    prefix="/clause-ssr",
    tags=["clause-ssr"],
    dependencies=[Depends(require_admin)],
)


class ClassificationWrite(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=400)
    category: str = Field(min_length=1, max_length=80)
    level: ClassificationLevel = "clause"
    customer_id: int | None = None


class ClassificationActiveWrite(BaseModel):
    active: bool
    customer_id: int | None = None


class DecisionWrite(BaseModel):
    classification_id: str = Field(min_length=1, max_length=200)
    unit_id: str = Field(min_length=1, max_length=200)
    answer: DecisionAnswer
    document_id: str | None = None
    customer_id: int | None = None
    source: str = "admin_queue"


class UndoWrite(BaseModel):
    classification_id: str = Field(min_length=1, max_length=200)
    document_id: str | None = None
    customer_id: int | None = None


class PromoteWrite(BaseModel):
    verification_id: str = Field(min_length=1, max_length=200)
    customer_id: int | None = None


class BuildSetWrite(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    customer_id: int | None = None
    holdout_ids: list[str] = Field(default_factory=list)
    max_per_polarity: int = Field(default=12, ge=1, le=50)


class MatchWrite(BaseModel):
    text_unit_id: str | None = None
    dense_vector: list[float] | None = None
    customer_id: int | None = None
    set_id: str | None = None
    k: int = Field(default=8, ge=1, le=50)


def _catalog() -> Catalog:
    runtime = get_runtime()
    if runtime is None:
        raise HTTPException(status_code=503, detail="overgraph_unavailable")
    return runtime.knowledge


def _scope(customer_id: int | None) -> KnowledgeTenantScope:
    return shared_scope() if customer_id is None else customer_scope(customer_id)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("/classifications")
async def api_list_classifications(
    customer_id: int | None = Query(default=None),
    active_only: bool = True,
) -> dict:
    catalog = _catalog()
    items = await asyncio.to_thread(
        list_classifications, catalog, customer_id=customer_id, active_only=active_only,
    )
    return {"items": [classification_json(item) for item in items]}


@router.post("/classifications")
async def api_upsert_classification(body: ClassificationWrite) -> dict:
    catalog = _catalog()
    try:
        item = await asyncio.to_thread(
            upsert_classification,
            catalog,
            scope=_scope(body.customer_id),
            slug=body.slug,
            question=body.question,
            category=body.category,
            level=body.level,
        )
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return classification_json(item)


@router.patch("/classifications/{classification_id}")
async def api_set_classification_active(
    classification_id: str, body: ClassificationActiveWrite,
) -> dict:
    catalog = _catalog()
    try:
        current = await asyncio.to_thread(get_classification, catalog, classification_id)
        item = await asyncio.to_thread(
            set_classification_active,
            catalog,
            current,
            scope=_scope(body.customer_id),
            active=body.active,
        )
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return classification_json(item)


@router.get("/queue")
async def api_queue(
    *,
    classification_id: str = Query(min_length=1, max_length=200),
    document_id: str | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=20),
    user: UserAccount = Depends(require_admin),
) -> dict:
    catalog = _catalog()
    try:
        page = await asyncio.to_thread(
            next_queue,
            catalog,
            scope=_scope(customer_id),
            classification_id=classification_id,
            reviewer_id=user.id,
            document_id=document_id,
            limit=limit,
        )
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return queue_json(page)


@router.post("/decisions")
async def api_record_decision(
    body: DecisionWrite, user: UserAccount = Depends(require_admin),
) -> dict:
    catalog = _catalog()
    scope = _scope(body.customer_id)
    try:
        verification = await asyncio.to_thread(
            record_decision,
            catalog,
            scope=scope,
            classification_id=body.classification_id,
            unit_id=body.unit_id,
            reviewer_id=user.id,
            answer=body.answer,
            source=body.source,
        )
        session = await asyncio.to_thread(
            get_or_create_session,
            catalog,
            scope=scope,
            reviewer_id=user.id,
            classification_id=body.classification_id,
            document_id=body.document_id,
        )
        session = await asyncio.to_thread(
            apply_decision, catalog, session, verification, scope=scope,
        )
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return {"verification": verification_json(verification), "session": session_json(session)}


@router.post("/decisions/undo")
async def api_undo(
    body: UndoWrite, user: UserAccount = Depends(require_admin),
) -> dict:
    catalog = _catalog()
    scope = _scope(body.customer_id)
    try:
        session = await asyncio.to_thread(
            get_or_create_session,
            catalog,
            scope=scope,
            reviewer_id=user.id,
            classification_id=body.classification_id,
            document_id=body.document_id,
        )
        session, unit_id = await asyncio.to_thread(undo_last, catalog, session, scope=scope)
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return {"session": session_json(session), "unit_id": unit_id}


@router.post("/anchors/promote")
async def api_promote(body: PromoteWrite) -> dict:
    catalog = _catalog()
    try:
        item = await asyncio.to_thread(
            promote_anchor,
            catalog,
            body.verification_id,
            scope=_scope(body.customer_id),
            embedding=catalog_embedding(catalog),
        )
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return anchor_json(item)


@router.get("/anchors")
async def api_list_anchors(
    customer_id: int | None = Query(default=None),
    classification_id: str | None = Query(default=None),
) -> dict:
    catalog = _catalog()
    items = await asyncio.to_thread(
        list_anchors,
        catalog,
        customer_id=customer_id,
        classification_id=classification_id,
    )
    return {"items": [anchor_json(item) for item in items]}


@router.post("/anchor-sets")
async def api_build_set(body: BuildSetWrite) -> dict:
    catalog = _catalog()
    try:
        item = await asyncio.to_thread(
            build_anchor_set,
            catalog,
            scope=_scope(body.customer_id),
            category=body.category,
            embedding=catalog_embedding(catalog),
            holdout_ids=tuple(body.holdout_ids),
            max_per_polarity=body.max_per_polarity,
        )
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return set_json(item)


@router.get("/anchor-sets")
async def api_list_sets(customer_id: int | None = Query(default=None)) -> dict:
    catalog = _catalog()
    items = await asyncio.to_thread(list_anchor_sets, catalog, customer_id=customer_id)
    return {"items": [set_json(item) for item in items]}


@router.post("/match")
async def api_match(body: MatchWrite) -> dict:
    catalog = _catalog()
    try:
        result = await asyncio.to_thread(
            match_query,
            catalog,
            scope=_scope(body.customer_id),
            embedding=catalog_embedding(catalog),
            vector=body.dense_vector,
            text_unit_id=body.text_unit_id,
            k=body.k,
            set_id=body.set_id,
        )
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return match_json(result)
