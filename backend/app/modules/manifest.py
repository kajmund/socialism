from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.modules.report_binding import ReportBinding


@dataclass(frozen=True)
class SpindoctorSource:
    """Module-owned report payload for Spinndoktor. Orchestration never inspects mode."""

    report: Report
    payload: Any
    bundles: list[Any] = field(default_factory=list)


SpindoctorSourceLoader = Callable[[AsyncSession, Report], Awaitable[SpindoctorSource]]
SpindoctorContextBuilder = Callable[..., str]


@dataclass(frozen=True)
class SpindoctorBinding:
    """Per-modul koppling in i Spinndoktor-lagret."""

    source_loader: SpindoctorSourceLoader
    context_builder: SpindoctorContextBuilder  # (source, *, locale, title) -> str
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
    prompt_defaults_provider: Callable[[], list] | None = None
    spindoctor: SpindoctorBinding | None = None
