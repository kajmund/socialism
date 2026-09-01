from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from fastapi import APIRouter

from app.modules.report_binding import ReportBinding


@dataclass(frozen=True)
class SpindoctorBinding:
    """Per-modul koppling in i Spinndoktor-lagret."""

    context_builder: Callable[..., str]  # same signature as build_dd_spindoctor_context_block
    mcp_tool_names: frozenset[str] = field(default_factory=frozenset)
    supports_interview: bool = False


@dataclass(frozen=True)
class ModuleManifest:
    id: str  # "dd", "politik", framtida "upphandling"
    name: str  # visningsnamn i GUI
    icon: str  # emoji eller ikon-key, för nav
    router: APIRouter  # monteras utan extra prefix (router bär sina egna)
    prompt_namespace: str  # Configuration.prompts[namespace]
    frontend_entry: str  # frontend route-namespace, t.ex. "dd"
    components: frozenset[str] = field(default_factory=frozenset)
    # kända components: "personas", "interview", "panel_engine", "spindoctor", "campaigns"
    report_modes: frozenset[str] = field(default_factory=frozenset)
    report: ReportBinding | None = None
    sub_questions_provider: Callable[[], list] | None = None
    expert_defaults_provider: Callable[[], list] | None = None
    spindoctor: SpindoctorBinding | None = None
