"""Ensure module-scoped panel catalog defaults from MODULE_REGISTRY providers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Kund
from app.modules.registry import MODULE_REGISTRY
from app.services.kund_store import ensure_default_kunder
from app.services.panel.expert_profiles_store import ensure_expert_profile_defaults
from app.services.panel.spinndoctor_profile import ensure_spinndoctor_profile
from app.services.panel.sub_questions_store import ensure_sub_question_defaults
from app.services.prompt_fields_store import (
    ensure_prompt_field_defaults,
    ensure_prompt_overrides_from_configurations,
)


async def _customer_ids(
    session: AsyncSession, customer_id: int | None
) -> list[int]:
    await ensure_default_kunder(session)
    if customer_id is not None:
        return [customer_id]
    result = await session.execute(select(Kund.id).order_by(Kund.id.asc()))
    return [int(row) for row in result.scalars().all()]


async def ensure_module_panel_defaults(
    session: AsyncSession, *, customer_id: int | None = None
) -> int:
    """Seed missing sub-questions, prompt catalog rows, and per-customer experts."""
    added = 0
    for module in MODULE_REGISTRY.values():
        if module.sub_questions_provider is not None:
            defaults = module.sub_questions_provider()
            added += await ensure_sub_question_defaults(session, module.id, defaults)
        if module.prompt_defaults_provider is not None:
            defaults = module.prompt_defaults_provider()
            added += await ensure_prompt_field_defaults(session, module.id, defaults)
    added += await ensure_prompt_overrides_from_configurations(session)

    for cid in await _customer_ids(session, customer_id):
        for module in MODULE_REGISTRY.values():
            if module.expert_defaults_provider is not None:
                defaults = module.expert_defaults_provider()
                added += await ensure_expert_profile_defaults(
                    session, module.id, defaults, customer_id=cid
                )
        added += await ensure_spinndoctor_profile(session, customer_id=cid)
    await session.commit()
    return added
