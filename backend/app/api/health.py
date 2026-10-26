from typing import Any

from fastapi import APIRouter, Request

from app.config import settings
from app.services.overgraph.owner_registry import (
    catalog_readiness,
    get_owner_registry,
    parse_memory_owner_route,
    parse_tenant_owner_sockets,
)
from app.services.overgraph.owner_runtime import get_owner_runtime

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/overgraph-owner")
async def overgraph_owner_health(request: Request) -> dict[str, Any]:
    """Live readiness: catches an owner that started after the backend or died."""
    status = await get_owner_runtime().refresh()
    status["tenant_owners"] = await get_owner_registry().health()
    status["catalogs"] = catalog_readiness(
        knowledge_owner=status.get("status") == "ready",
        tenant_routes=len(parse_tenant_owner_sockets(
            settings.overgraph_tenant_owner_sockets,
        )),
        memory_owner=bool(parse_memory_owner_route(settings.overgraph_memory_owner_socket)),
    )
    request.app.state.overgraph_owner = status
    return status


@router.get("/health/research-vector")
async def research_vector_health(request: Request) -> dict[str, Any]:
    return dict(getattr(request.app.state, "research_vector", {"status": "not_started"}))
