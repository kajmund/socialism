"""Build Spinndoktor system context from report artifacts and run data."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.modules.manifest import SpindoctorSource
from app.modules.registry import MODULE_REGISTRY, module_id_for_report_mode
from app.services.report.bundles import RunBundle
from app.services.report.locale import normalize_locale


async def _ready_report(session: AsyncSession, report_id: str) -> Report:
    report = await session.get(Report, report_id)
    if report is None:
        raise ValueError(f"Report {report_id!r} not found")
    if report.status != "succeeded":
        raise ValueError(f"Report {report_id!r} is not ready (status={report.status})")
    sources = report.sources if isinstance(report.sources, list) else []
    if not sources:
        raise ValueError(f"Report {report_id!r} has no sources")
    return report


def _spindoctor_binding(mode: str):
    module_id = module_id_for_report_mode(mode)
    binding = MODULE_REGISTRY[module_id].spindoctor
    if binding is None:
        raise RuntimeError(f"Module {module_id!r} has no spindoctor binding")
    return binding


async def load_ready_spindoctor_source(
    session: AsyncSession,
    *,
    report_id: str,
) -> SpindoctorSource:
    """Load a ready report through the owning module's source_loader."""
    report = await _ready_report(session, report_id)
    binding = _spindoctor_binding(report.mode)
    return await binding.source_loader(session, report)


async def load_spindoctor_source(
    session: AsyncSession,
    *,
    report_id: str,
) -> tuple[Report, list[RunBundle]]:
    """Compat wrapper for MCP/tools that still want (report, bundles)."""
    source = await load_ready_spindoctor_source(session, report_id=report_id)
    return source.report, source.bundles


async def build_spindoctor_context(
    session: AsyncSession,
    *,
    report_id: str,
) -> tuple[Report, str]:
    """Return report row and formatted context block for the system prompt."""
    source = await load_ready_spindoctor_source(session, report_id=report_id)
    locale = normalize_locale(source.report.locale or "sv")
    binding = _spindoctor_binding(source.report.mode)
    context = binding.context_builder(
        source,
        locale=locale,
        title=source.report.title or report_id,
    )
    return source.report, context
