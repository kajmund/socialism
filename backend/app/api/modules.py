"""Public product-module metadata from MODULE_REGISTRY."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.database.models import UserAccount
from app.modules.registry import MODULE_REGISTRY, serialize_module
from app.schemas.modules import ModuleOut

router = APIRouter(prefix="/modules", tags=["modules"])


@router.get("", response_model=list[ModuleOut])
async def list_modules(
    _user: UserAccount = Depends(get_current_user),
) -> list[ModuleOut]:
    return [ModuleOut.model_validate(serialize_module(module)) for module in MODULE_REGISTRY.values()]
