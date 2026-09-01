"""Politik module report generator — owned by the politik ModuleManifest ReportBinding."""

from __future__ import annotations

from app.modules.report_binding import ReportGenerateContext, ReportGenerateResult
from app.services.anchor_calibration import anchor_validation_for_report
from app.services.anchor_store import require_anchor_sets_for_language
from app.services.prompt_store import (
    require_active_report_thresholds,
    require_active_ssr_temperature,
)
from app.services.report import bundles as report_bundles
from app.services.report.generate import generate_report_html


async def generate_politik_module_report(ctx: ReportGenerateContext) -> ReportGenerateResult:
    async with ctx.session_factory() as session:
        bundles = await report_bundles.build_bundles(session, ctx.sources)
        ssr_temperature = await require_active_ssr_temperature(session)
        report_thresholds = await require_active_report_thresholds(session)
        resolved_anchors = await require_anchor_sets_for_language(
            session, "en" if ctx.locale == "en" else "sv"
        )
        anchor_validation = await anchor_validation_for_report(
            session,
            tone_row=resolved_anchors["tone_row"],
            style_row=resolved_anchors["style_row"],
        )

    html_path, slots_path, _slots, timing = await generate_report_html(
        bundles,
        out_dir=ctx.out_dir,
        title=ctx.title,
        locale=ctx.locale,
        ssr_temperature=ssr_temperature,
        report_thresholds=report_thresholds,
        resolved_anchors=resolved_anchors,
        anchor_validation=anchor_validation,
    )
    return ReportGenerateResult(
        html_path=html_path,
        slots_path=slots_path,
        timing=timing,
    )
