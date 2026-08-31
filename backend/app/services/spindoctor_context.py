"""Build Spinndoktor system context from report artifacts and run data."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report
from app.modules.registry import MODULE_REGISTRY, module_id_for_report_mode
from app.services.report.bundles import RunBundle, build_bundles
from app.services.report.locale import normalize_locale
from app.services.spindoctor_dd import load_dd_report_json


async def load_spindoctor_source(
    session: AsyncSession,
    *,
    report_id: str,
) -> tuple[Report, list[RunBundle]]:
    """Load a ready report and its run bundles. Raises ValueError if not usable."""
    report = await session.get(Report, report_id)
    if report is None:
        raise ValueError(f"Report {report_id!r} not found")
    if report.status != "succeeded":
        raise ValueError(f"Report {report_id!r} is not ready (status={report.status})")
    sources = report.sources if isinstance(report.sources, list) else []
    if not sources:
        raise ValueError(f"Report {report_id!r} has no sources")
    if report.mode == "dd":
        if load_dd_report_json(report_id) is None:
            raise ValueError(f"report.dd.json not found for {report_id!r}")
        return report, []
    return report, await build_bundles(session, sources)


async def build_spindoctor_context(
    session: AsyncSession,
    *,
    report_id: str,
) -> tuple[Report, str]:
    """Return report row and formatted context block for the system prompt."""
    report, bundles = await load_spindoctor_source(session, report_id=report_id)
    locale = normalize_locale(report.locale or "sv")
    module_id = module_id_for_report_mode(report.mode)
    binding = MODULE_REGISTRY[module_id].spindoctor
    if binding is None:
        raise RuntimeError(f"Module {module_id!r} has no spindoctor binding")

    if report.mode == "dd":
        dd_doc = load_dd_report_json(report_id)
        if dd_doc is None:
            raise ValueError(f"report.dd.json not found for {report_id!r}")
        context = binding.context_builder(
            dd_doc,
            locale=locale,
            title=report.title or report_id,
        )
        return report, context

    sources = report.sources if isinstance(report.sources, list) else []
    context = binding.context_builder(
        title=report.title or report_id,
        locale=locale,
        sources=sources,
        bundles=bundles,
        report_id=report_id,
    )
    return report, context
