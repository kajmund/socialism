"""Declared product modules — source of truth for module router mounting."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    anchor_sets,
    dd,
    expertgranskning,
    label_vocabularies,
    messages,
    playground,
    rattsunderlag,
    runs,
)
from app.modules.manifest import ModuleManifest, SpindoctorBinding
from app.modules.report_binding import ReportBinding, UnknownReportModeError
from app.services.dd.company_mcp import COMPANY_TOOL_NAMES
from app.services.dd.default_experts import DEFAULT_EXPERT_SPECS
from app.services.dd.module_report import generate_dd_module_report
from app.services.dd.sub_questions import DD_SUB_QUESTION_DEFAULTS
from app.services.expertgranskning.module_report import generate_expertgranskning_module_report
from app.services.expertgranskning.spindoctor import (
    build_expertgranskning_spindoctor_context_from_source,
    load_expertgranskning_spindoctor_source,
)
from app.services.rattsunderlag.module_report import generate_rattsunderlag_module_report
from app.services.rattsunderlag.spindoctor import (
    build_rattsunderlag_spindoctor_context_from_source,
    load_rattsunderlag_spindoctor_source,
)
from app.services.prompt_defaults import (
    dd_prompt_defaults,
    expertgranskning_prompt_defaults,
    politik_prompt_defaults,
    rattsunderlag_prompt_defaults,
)
from app.services.report.politik_module_report import generate_politik_module_report
from app.services.spindoctor_dd import (
    build_dd_spindoctor_context_from_source,
    load_dd_spindoctor_source,
)
from app.services.spindoctor_politik import (
    build_politik_spindoctor_context_from_source,
    load_politik_spindoctor_source,
)
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
        components=frozenset({"personas", "panel_engine", "spindoctor", "campaigns"}),
        report_modes=frozenset({"dd"}),
        report=ReportBinding(
            source_types=frozenset({"dd_session"}),
            generate=generate_dd_module_report,
        ),
        sub_questions_provider=lambda: list(DD_SUB_QUESTION_DEFAULTS),
        expert_defaults_provider=lambda: list(DEFAULT_EXPERT_SPECS),
        prompt_defaults_provider=dd_prompt_defaults,
        spindoctor=SpindoctorBinding(
            source_loader=load_dd_spindoctor_source,
            context_builder=build_dd_spindoctor_context_from_source,
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
        report_modes=frozenset({"quick", "full"}),
        report=ReportBinding(
            source_types=frozenset({"oasis"}),
            generate=generate_politik_module_report,
        ),
        prompt_defaults_provider=politik_prompt_defaults,
        spindoctor=SpindoctorBinding(
            source_loader=load_politik_spindoctor_source,
            context_builder=build_politik_spindoctor_context_from_source,
            mcp_tool_names=frozenset({"get_report_ssr"}) | SPINDOCTOR_OASIS_TOOL_NAMES,
            supports_interview=True,
        ),
    ),
    "expertgranskning": ModuleManifest(
        id="expertgranskning",
        name="Expertgranskning",
        icon="📝",
        router=expertgranskning.router,
        prompt_namespace="expertgranskning",
        frontend_entry="expertgranskning",
        components=frozenset({"panel_engine", "spindoctor"}),
        report_modes=frozenset({"expertgranskning"}),
        report=ReportBinding(
            source_types=frozenset({"expertgranskning_session"}),
            generate=generate_expertgranskning_module_report,
        ),
        prompt_defaults_provider=expertgranskning_prompt_defaults,
        spindoctor=SpindoctorBinding(
            source_loader=load_expertgranskning_spindoctor_source,
            context_builder=build_expertgranskning_spindoctor_context_from_source,
            supports_interview=False,
        ),
    ),
    "rattsunderlag": ModuleManifest(
        id="rattsunderlag",
        name="Rättsunderlag",
        icon="⚖️",
        router=rattsunderlag.router,
        prompt_namespace="rattsunderlag",
        frontend_entry="modules/rattsunderlag",
        components=frozenset(),
        report_modes=frozenset({"rattsunderlag"}),
        report=ReportBinding(
            source_types=frozenset({"rattsunderlag"}),
            generate=generate_rattsunderlag_module_report,
        ),
        prompt_defaults_provider=rattsunderlag_prompt_defaults,
        spindoctor=SpindoctorBinding(
            source_loader=load_rattsunderlag_spindoctor_source,
            context_builder=build_rattsunderlag_spindoctor_context_from_source,
            supports_interview=False,
        ),
    ),
}


def module_id_for_report_mode(mode: str) -> str:
    """Map Report.mode to a MODULE_REGISTRY key. Fail loud — no politik fallback."""
    matches = [m.id for m in MODULE_REGISTRY.values() if mode in m.report_modes]
    if len(matches) != 1:
        raise UnknownReportModeError(mode, matches=matches)
    return matches[0]


def source_types_for_registry(
    registry: dict[str, ModuleManifest] | None = None,
) -> dict[str, frozenset[str]]:
    """Map each report source type to the report_modes that accept it."""
    source = registry if registry is not None else MODULE_REGISTRY
    mapping: dict[str, set[str]] = {}
    for module in source.values():
        if module.report is None:
            continue
        for source_type in module.report.source_types:
            mapping.setdefault(source_type, set()).update(module.report_modes)
    return {key: frozenset(modes) for key, modes in mapping.items()}


def resolve_report_mode(source_type: str, requested: str | None) -> str:
    """Infer or validate Report.mode from a source type via the registry."""
    modes = source_types_for_registry().get(source_type)
    if not modes:
        raise UnknownReportModeError(requested or source_type)
    if requested is None:
        if len(modes) == 1:
            return next(iter(modes))
        if "quick" in modes:
            return "quick"
        raise ValueError(f"mode is required for source type {source_type!r}")
    if requested not in modes:
        raise ValueError(
            f"mode {requested!r} is not valid for source type {source_type!r}"
        )
    return requested


def report_binding_for_mode(mode: str) -> ReportBinding:
    module_id = module_id_for_report_mode(mode)
    binding = MODULE_REGISTRY[module_id].report
    if binding is None:
        raise UnknownReportModeError(mode)
    return binding


def assert_unique_report_modes(registry: dict[str, ModuleManifest] | None = None) -> None:
    """Startup guard: each Report.mode belongs to exactly one module."""
    source = registry if registry is not None else MODULE_REGISTRY
    seen: dict[str, str] = {}
    for module in source.values():
        if module.report_modes and module.report is None:
            raise RuntimeError(
                f"Module {module.id!r} declares report_modes {sorted(module.report_modes)} "
                "but has no ReportBinding"
            )
        if module.report is not None and not module.report_modes:
            raise RuntimeError(
                f"Module {module.id!r} has ReportBinding but empty report_modes"
            )
        for mode in module.report_modes:
            if mode in seen:
                raise RuntimeError(
                    f"Report mode {mode!r} claimed by both {seen[mode]!r} and {module.id!r}"
                )
            seen[mode] = module.id


assert_unique_report_modes()


def serialize_module(module: ModuleManifest) -> dict[str, object]:
    """Public module metadata — no routers or callables."""
    return {
        "id": module.id,
        "name": module.name,
        "icon": module.icon,
        "prompt_namespace": module.prompt_namespace,
        "frontend_entry": module.frontend_entry,
        "components": sorted(module.components),
        "report_modes": sorted(module.report_modes),
        "has_sub_questions": module.sub_questions_provider is not None,
        "has_expert_defaults": module.expert_defaults_provider is not None,
        "has_prompt_defaults": module.prompt_defaults_provider is not None,
        "supports_interview": bool(module.spindoctor and module.spindoctor.supports_interview),
    }


def module_has_component(module_id: str, component: str) -> bool:
    manifest = MODULE_REGISTRY.get(module_id)
    return manifest is not None and component in manifest.components
