"""Admin read API for the embedded OverGraph catalogs."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import require_admin
from app.services.overgraph.browse import (
    catalog_summary, list_nodes, node_detail, node_summary,
)
from app.services.overgraph.catalogs import Catalog, get_runtime
from app.services.overgraph.owner import OwnerProtocolError, OwnerUnavailable
from app.services.overgraph.owner_runtime import get_owner_runtime

CatalogName = Literal["knowledge", "memory"]

router = APIRouter(
    prefix="/overgraph",
    tags=["overgraph"],
    dependencies=[Depends(require_admin)],
)


class OwnerQuery(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    props: dict[str, str] = Field(default_factory=dict)
    include_vectors: bool = False
    limit: int = Field(default=50, ge=1, le=100)
    after: int | None = Field(default=None, ge=0)


def _owner_client():
    client = get_owner_runtime().client
    if client is None:
        raise HTTPException(status_code=503, detail="overgraph_owner_unavailable")
    return client


def _owner_node(row: dict, *, include_vectors: bool) -> dict:
    node = node_summary(
        id=int(row["id"]), key=str(row["key"]), labels=list(row["labels"]),
        props=dict(row.get("props") or {}),
    )
    result = {**node, "props": dict(row.get("props") or {})}
    if include_vectors:
        result["dense_vector"] = row.get("dense_vector")
    return result


def _catalog(kind: CatalogName) -> Catalog:
    runtime = get_runtime()
    if runtime is None:
        raise HTTPException(status_code=503, detail="overgraph_unavailable")
    if kind == "knowledge":
        return runtime.knowledge
    return runtime.memory


@router.get("")
async def overgraph_catalogs() -> dict:
    runtime = get_runtime()
    if runtime is None:
        raise HTTPException(status_code=503, detail="overgraph_unavailable")
    owner = get_owner_runtime().client
    if owner is not None:
        knowledge = {
            "kind": "knowledge",
            "access": "owner",
            "catalog_id": owner.catalog_id,
            "node_labels": [],
            "edge_labels": [],
        }
        memory = await asyncio.to_thread(catalog_summary, runtime.memory)
        return {"catalogs": [knowledge, memory]}
    knowledge, memory = await asyncio.gather(
        asyncio.to_thread(catalog_summary, runtime.knowledge),
        asyncio.to_thread(catalog_summary, runtime.memory),
    )
    return {"catalogs": [knowledge, memory]}


@router.post("/{kind}/query")
async def overgraph_query(kind: CatalogName, body: OwnerQuery) -> dict:
    """Bounded owner-backed node query (knowledge) with stable cursor."""
    if kind == "knowledge" and get_owner_runtime().client is not None:
        if len(body.props) > 8:
            raise HTTPException(status_code=400, detail="too_many_props")
        try:
            page = await _owner_client().query_nodes(
                body.label, props=body.props, include_vectors=body.include_vectors,
                limit=body.limit, after=body.after,
            )
        except OwnerUnavailable as exc:
            raise HTTPException(status_code=503, detail="overgraph_owner_unavailable") from exc
        except OwnerProtocolError as exc:
            raise HTTPException(status_code=502, detail=f"overgraph_owner_read_failed: {exc}") from exc
        return {
            "nodes": [
                _owner_node(row, include_vectors=body.include_vectors)
                for row in page["nodes"]
            ],
            "next_cursor": page["next_cursor"],
            "read_revision": page.get("read_revision"),
            "access": "owner",
        }
    if kind == "memory":
        rows = await asyncio.to_thread(
            list_nodes, _catalog("memory"), label=body.label, query="", limit=body.limit,
            after=body.after,
        )
        return {**rows, "access": "local"}
    raise HTTPException(status_code=503, detail="overgraph_owner_unavailable")


@router.get("/{kind}/nodes")
async def overgraph_nodes(
    kind: CatalogName,
    *,
    label: str = Query(min_length=1, max_length=200),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=40, ge=1, le=100),
    after: int | None = Query(default=None, ge=0),
) -> dict:
    if kind == "knowledge" and get_owner_runtime().client is not None:
        if q.strip():
            raise HTTPException(status_code=400, detail="query_not_supported_owner_mode")
        try:
            page = await _owner_client().query_nodes(label, limit=limit, after=after)
        except OwnerUnavailable as exc:
            raise HTTPException(status_code=503, detail="overgraph_owner_unavailable") from exc
        except OwnerProtocolError as exc:
            raise HTTPException(status_code=502, detail=f"overgraph_owner_read_failed: {exc}") from exc
        return {
            "nodes": [_owner_node(row, include_vectors=False) for row in page["nodes"]],
            "next_cursor": page["next_cursor"],
            "read_revision": page.get("read_revision"),
            "access": "owner",
        }
    return await asyncio.to_thread(
        list_nodes, _catalog(kind), label=label, query=q, limit=limit, after=after,
    )


@router.get("/{kind}/nodes/{node_id}")
async def overgraph_node(kind: CatalogName, node_id: int) -> dict:
    if kind == "knowledge" and get_owner_runtime().client is not None:
        try:
            row = await _owner_client().node(node_id)
        except OwnerUnavailable as exc:
            raise HTTPException(status_code=503, detail="overgraph_owner_unavailable") from exc
        except OwnerProtocolError as exc:
            raise HTTPException(status_code=502, detail=f"overgraph_owner_read_failed: {exc}") from exc
        if row is None:
            raise HTTPException(status_code=404, detail="overgraph_node_not_found")
        return _owner_node(row, include_vectors=True) | {
            "edges": row.get("edges") or [],
            "access": "owner",
        }
    detail = await asyncio.to_thread(node_detail, _catalog(kind), node_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="overgraph_node_not_found")
    return detail
