"""Declared product modules — source of truth for module router mounting."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    anchor_sets,
    dd,
    label_vocabularies,
    messages,
    playground,
    runs,
)
from app.modules.manifest import ModuleManifest, SpindoctorBinding
from app.services.dd.company_mcp import COMPANY_TOOL_NAMES
from app.services.dd.default_experts import DEFAULT_EXPERT_SPECS
from app.services.dd.sub_questions import DD_SUB_QUESTION_DEFAULTS
from app.services.spindoctor_dd import build_dd_spindoctor_context_block
from app.services.spindoctor_politik import build_politik_spindoctor_context_block
from app.services.spindoctor_tool_names import SPINDOCTOR_OASIS_TOOL_NAMES

_politik_router = APIRouter(tags=["politik"])
_politik_router.include_router(runs.router)
_politik_router.include_router(messages.router)
_politik_router.include_router(anchor_sets.router)
_politik_router.include_router(label_vocabularies.router)
_politik_router.include_router(playground.router)


MODULE_REGISTRY: dict[str, ModuleManifest] = {
    "dd": ModuleManifest(
        id="dd",
        name="Due Diligence",
        icon="🔍",
        router=dd.router,
        prompt_namespace="dd",
        frontend_entry="dd",
        components=frozenset({"personas", "panel_engine", "spindoctor"}),
        sub_questions_provider=lambda: list(DD_SUB_QUESTION_DEFAULTS),
        expert_defaults_provider=lambda: list(DEFAULT_EXPERT_SPECS),
        spindoctor=SpindoctorBinding(
            context_builder=build_dd_spindoctor_context_block,
            mcp_tool_names=frozenset({"get_report_dd"}) | COMPANY_TOOL_NAMES,
            supports_interview=False,
        ),
    ),
    "politik": ModuleManifest(
        id="politik",
        name="Politisk simulering",
        icon="🗳️",
        router=_politik_router,
        prompt_namespace="politik",
        frontend_entry="politik",
        components=frozenset({"personas", "interview", "spindoctor"}),
        spindoctor=SpindoctorBinding(
            context_builder=build_politik_spindoctor_context_block,
            mcp_tool_names=frozenset({"get_report_ssr"}) | SPINDOCTOR_OASIS_TOOL_NAMES,
            supports_interview=True,
        ),
    ),
}


def module_id_for_report_mode(mode: str) -> str:
    """Map Report.mode to a MODULE_REGISTRY key."""
    return "dd" if mode == "dd" else "politik"
