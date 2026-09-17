from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/research-vector")
async def research_vector_health(request: Request) -> dict[str, Any]:
    return dict(getattr(request.app.state, "research_vector", {"status": "not_started"}))
