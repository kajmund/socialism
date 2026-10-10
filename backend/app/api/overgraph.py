"""Admin read API for the embedded OverGraph catalogs."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import require_admin
from app.services.overgraph.browse import catalog_summary, list_nodes, node_detail
from app.services.overgraph.catalogs import Catalog, get_runtime

CatalogName = Literal["knowledge", "memory"]

router = APIRouter(
    prefix="/overgraph",
    tags=["overgraph"],
    dependencies=[Depends(require_admin)],
)


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
    knowledge, memory = await asyncio.gather(
        asyncio.to_thread(catalog_summary, runtime.knowledge),
        asyncio.to_thread(catalog_summary, runtime.memory),
    )
    return {"catalogs": [knowledge, memory]}


@router.get("/{kind}/nodes")
async def overgraph_nodes(
    kind: CatalogName,
    *,
    label: str = Query(min_length=1, max_length=200),
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=40, ge=1, le=100),
    after: int | None = Query(default=None, ge=0),
) -> dict:
    return await asyncio.to_thread(
        list_nodes, _catalog(kind), label=label, query=q, limit=limit, after=after,
    )


@router.get("/{kind}/nodes/{node_id}")
async def overgraph_node(kind: CatalogName, node_id: int) -> dict:
    detail = await asyncio.to_thread(node_detail, _catalog(kind), node_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="overgraph_node_not_found")
    return detail
