"""Ensure module-scoped panel catalog defaults from MODULE_REGISTRY providers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.registry import MODULE_REGISTRY
from app.services.panel.expert_profiles_store import ensure_expert_profile_defaults
from app.services.panel.spinndoctor_profile import ensure_spinndoctor_profile
from app.services.panel.sub_questions_store import ensure_sub_question_defaults


async def ensure_module_panel_defaults(session: AsyncSession) -> int:
    """Seed missing sub-questions and expert profiles for modules with providers."""
    added = 0
    for module in MODULE_REGISTRY.values():
        if module.sub_questions_provider is not None:
            defaults = module.sub_questions_provider()
            added += await ensure_sub_question_defaults(session, module.id, defaults)
        if module.expert_defaults_provider is not None:
            defaults = module.expert_defaults_provider()
            added += await ensure_expert_profile_defaults(session, module.id, defaults)
    added += await ensure_spinndoctor_profile(session)
    return added
