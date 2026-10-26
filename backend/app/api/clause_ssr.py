"""Opt-in admin API for the clause SSR library. Isolated from research/SWE."""

from __future__ import annotations

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import require_admin
from app.database.models import UserAccount
from app.services.knowledge.scope import KnowledgeTenantScope, customer_scope, shared_scope
from app.services.overgraph.catalogs import Catalog, get_runtime
from app.services.overgraph.owner import OwnerUnavailable
from app.services.overgraph.owner_runtime import get_owner_runtime

from app.services.clause_ssr.anchors import list_anchors
from app.services.clause_ssr.repository import ClauseRepository
from app.services.clause_ssr.classifications import (
    get_classification,
    list_classifications,
    set_classification_active,
    upsert_classification,
)
from app.services.clause_ssr.match import match_query
from app.services.clause_ssr.queue import next_queue
from app.services.clause_ssr import owner_match, owner_select
from app.services.clause_ssr.select import list_anchor_sets
from app.services.clause_ssr.serialize import (
    anchor_json,
    classification_json,
    match_json,
    queue_json,
    session_json,
    set_json,
    verification_json,
)
from app.services.clause_ssr.spec import catalog_embedding
from app.services.clause_ssr.types import Anchor, AnchorSet, ClassificationLevel, DecisionAnswer, EmbeddingSpec, ReviewSession, Verification

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
    scope = _scope(customer_id)
    try:
        repository = ClauseRepository(get_owner_runtime().require_client())
        session_props = await repository.get_or_create_session(
            scope=scope, reviewer_id=user.id,
            classification_id=classification_id, document_id=document_id,
        )
        session = ReviewSession(
            id=str(session_props.get("id") or ""), reviewer_id=user.id,
            classification_id=classification_id,
            document_id=str(session_props.get("document_id") or "") or None,
            last_unit_id=str(session_props.get("last_unit_id") or "") or None,
            last_verification_id=str(session_props.get("last_verification_id") or "") or None,
            decided_yes=int(session_props.get("decided_yes") or 0),
            decided_no=int(session_props.get("decided_no") or 0),
            skipped=int(session_props.get("skipped") or 0),
            unsure=int(session_props.get("unsure") or 0),
            scope_key=scope.scope_key,
        )
        page = await asyncio.to_thread(
            next_queue,
            catalog,
            scope=scope,
            classification_id=classification_id,
            reviewer_id=user.id,
            document_id=document_id,
            limit=limit,
            session=session,
        )
    except OwnerUnavailable as exc:
        raise HTTPException(status_code=503, detail="overgraph_owner_unavailable") from exc
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return queue_json(page)


@router.post("/decisions")
async def api_record_decision(
    body: DecisionWrite, user: UserAccount = Depends(require_admin),
) -> dict:
    scope = _scope(body.customer_id)
    try:
        repository = ClauseRepository(get_owner_runtime().require_client())
        result = await repository.record_decision(
            scope=scope,
            classification_id=body.classification_id,
            unit_id=body.unit_id,
            reviewer_id=user.id,
            answer=body.answer,
            document_id=body.document_id,
        )
    except OwnerUnavailable as exc:
        raise HTTPException(status_code=503, detail="overgraph_owner_unavailable") from exc
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    v = dict(result["verification"])
    s = dict(result["session"])
    v.setdefault("id", "")
    verification = Verification(
        id=str(v.get("id") or ""), source_unit_id=str(v.get("source_unit_id") or ""),
        source_document_id=str(v.get("source_document_id") or ""),
        content_hash=str(v.get("content_hash") or ""),
        classification_id=str(v.get("classification_id") or ""),
        classification_version=int(v.get("classification_version") or 1),
        question=str(v.get("question") or ""), category=str(v.get("category") or ""),
        answer=str(v.get("answer") or "skip"), polarity=(str(v.get("polarity")) or None),
        reviewer_id=str(v.get("reviewer_id") or ""), decided_at_ms=int(v.get("decided_at_ms") or 0),
        source=str(v.get("source") or "admin_queue"), revision=int(v.get("revision") or 1),
        status=str(v.get("status") or "active"), scope_key=str(v.get("scope_key") or ""),
    )
    session = ReviewSession(
        id=str(s.get("id") or ""), reviewer_id=str(s.get("reviewer_id") or user.id),
        classification_id=str(s.get("classification_id") or body.classification_id),
        document_id=str(s.get("document_id") or "") or None,
        last_unit_id=str(s.get("last_unit_id") or "") or None,
        last_verification_id=str(s.get("last_verification_id") or "") or None,
        decided_yes=int(s.get("decided_yes") or 0), decided_no=int(s.get("decided_no") or 0),
        skipped=int(s.get("skipped") or 0), unsure=int(s.get("unsure") or 0),
        scope_key=str(s.get("scope_key") or scope.scope_key),
    )
    return {"verification": verification_json(verification), "session": session_json(session)}


@router.post("/decisions/undo")
async def api_undo(
    body: UndoWrite, user: UserAccount = Depends(require_admin),
) -> dict:
    scope = _scope(body.customer_id)
    try:
        repository = ClauseRepository(get_owner_runtime().require_client())
        session_props, unit_id = await repository.undo_last(
            scope=scope, reviewer_id=user.id,
            classification_id=body.classification_id, document_id=body.document_id,
        )
    except OwnerUnavailable as exc:
        raise HTTPException(status_code=503, detail="overgraph_owner_unavailable") from exc
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    if session_props is None:
        return {"session": None, "unit_id": None}
    session = ReviewSession(
        id=str(session_props.get("id") or ""), reviewer_id=user.id,
        classification_id=body.classification_id,
        document_id=str(session_props.get("document_id") or "") or None,
        last_unit_id=None, last_verification_id=None,
        decided_yes=int(session_props.get("decided_yes") or 0),
        decided_no=int(session_props.get("decided_no") or 0),
        skipped=int(session_props.get("skipped") or 0), unsure=int(session_props.get("unsure") or 0),
        scope_key=scope.scope_key,
    )
    return {"session": session_json(session), "unit_id": unit_id}


@router.post("/anchors/promote")
async def api_promote(body: PromoteWrite) -> dict:
    scope = _scope(body.customer_id)
    try:
        repository = ClauseRepository(get_owner_runtime().require_client())
        props = await repository.promote_anchor(
            scope=scope, verification_id=body.verification_id,
            embedding=catalog_embedding(_catalog()),
        )
    except OwnerUnavailable as exc:
        raise HTTPException(status_code=503, detail="overgraph_owner_unavailable") from exc
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    anchor = Anchor(
        id=str(props.get("id") or ""), verification_id=str(props.get("verification_id") or ""),
        source_unit_id=str(props.get("source_unit_id") or ""),
        classification_id=str(props.get("classification_id") or ""),
        category=str(props.get("category") or ""), polarity=str(props.get("polarity") or "positive"),
        content_hash=str(props.get("content_hash") or ""), status=str(props.get("status") or "draft"),
        embedding=EmbeddingSpec(
            model=str(props.get("embedding_model") or ""),
            revision=str(props.get("embedding_revision") or ""),
            dimension=int(props.get("embedding_dimension") or 0),
        ),
        vector=None, scope_key=str(props.get("scope_key") or ""),
        provenance={"reviewer_id": str(props.get("reviewer_id") or ""), "question": str(props.get("question") or "")},
    )
    return anchor_json(anchor)


@router.get("/anchors")
async def api_list_anchors(
    customer_id: int | None = Query(default=None),
    classification_id: str | None = Query(default=None),
) -> dict:
    owner = get_owner_runtime().client
    if owner is not None:
        items = await owner_select.list_anchors(
            owner, customer_id=customer_id, classification_id=classification_id,
        )
    else:
        items = await asyncio.to_thread(
            list_anchors,
            _catalog(),
            customer_id=customer_id,
            classification_id=classification_id,
        )
    return {"items": [anchor_json(item) for item in items]}


@router.post("/anchor-sets")
async def api_build_set(body: BuildSetWrite) -> dict:
    scope = _scope(body.customer_id)
    try:
        repository = ClauseRepository(get_owner_runtime().require_client())
        props = await repository.build_anchor_set(
            scope=scope, category=body.category,
            embedding=catalog_embedding(_catalog()),
            holdout_ids=tuple(body.holdout_ids),
            max_per_polarity=body.max_per_polarity,
        )
    except OwnerUnavailable as exc:
        raise HTTPException(status_code=503, detail="overgraph_owner_unavailable") from exc
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    item = AnchorSet(
        id=str(props.get("id") or ""), version=int(props.get("version") or 1),
        category=str(props.get("category") or ""), status=str(props.get("status") or "active"),
        selection_method="deterministic_diversity",
        embedding=EmbeddingSpec(
            model=str(props.get("embedding_model") or ""),
            revision=str(props.get("embedding_revision") or ""),
            dimension=int(props.get("embedding_dimension") or 0),
        ),
        holdout_ids=tuple(item for item in str(props.get("holdout_ids") or "").split(",") if item),
        member_ids=tuple(props.get("member_ids") or ()),
        scope_key=scope.scope_key, created_at_ms=int(props.get("created_at_ms") or 0),
    )
    return set_json(item)


@router.post("/anchors/mark-stale")
async def api_mark_stale(customer_id: int | None = Query(default=None)) -> dict:
    scope = _scope(customer_id)
    try:
        repository = ClauseRepository(get_owner_runtime().require_client())
        changed = await repository.mark_stale_embeddings(
            scope=scope, expected=catalog_embedding(_catalog()),
        )
    except OwnerUnavailable as exc:
        raise HTTPException(status_code=503, detail="overgraph_owner_unavailable") from exc
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return {"changed": changed}


@router.get("/anchor-sets")
async def api_list_sets(customer_id: int | None = Query(default=None)) -> dict:
    owner = get_owner_runtime().client
    if owner is not None:
        items = await owner_select.list_anchor_sets(owner, customer_id=customer_id)
    else:
        items = await asyncio.to_thread(
            list_anchor_sets, _catalog(), customer_id=customer_id,
        )
    return {"items": [set_json(item) for item in items]}


@router.post("/match")
async def api_match(body: MatchWrite) -> dict:
    owner = get_owner_runtime().client
    scope = _scope(body.customer_id)
    try:
        if owner is not None:
            result = await owner_match.match_query(
                owner,
                scope=scope,
                embedding=catalog_embedding(_catalog()),
                vector=body.dense_vector,
                text_unit_id=body.text_unit_id,
                k=body.k,
                set_id=body.set_id,
            )
        else:
            catalog = _catalog()
            result = await asyncio.to_thread(
                match_query,
                catalog,
                scope=scope,
                embedding=catalog_embedding(catalog),
                vector=body.dense_vector,
                text_unit_id=body.text_unit_id,
                k=body.k,
                set_id=body.set_id,
            )
    except (PermissionError, KeyError, ValueError) as exc:
        raise _http(exc) from exc
    return match_json(result)
