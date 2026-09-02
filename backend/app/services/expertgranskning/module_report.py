"""Expertgranskning report generator — owned by the ModuleManifest ReportBinding."""

from __future__ import annotations

from app.modules.report_binding import ReportGenerateContext, ReportGenerateResult
from app.services.expertgranskning import SOURCE_TYPE
from app.services.expertgranskning.report_html import write_expertgranskning_artifacts
from app.services.expertgranskning.sessions import (
    document_text_from_config,
    is_expertgranskning_session,
)
from app.services.panel.sessions import get_panel_session


async def generate_expertgranskning_module_report(
    ctx: ReportGenerateContext,
) -> ReportGenerateResult:
    sources = ctx.sources
    if len(sources) != 1 or sources[0].get("type") != SOURCE_TYPE:
        raise ValueError("Expertgranskning report requires exactly one expertgranskning_session source")
    session_id = str(sources[0]["session_id"])
    async with ctx.session_factory() as session:
        panel = await get_panel_session(session, session_id)
        if panel is None:
            raise ValueError(f"Panel session not found: {session_id}")
        if not is_expertgranskning_session(panel):
            raise ValueError("Panel session is not an expertgranskning generic_panel")
        if panel.status != "succeeded":
            raise ValueError("Panel session has not succeeded")
        result = panel.result if isinstance(panel.result, dict) else None
        if result is None:
            raise ValueError("Panel session has no result")
        config = panel.config if isinstance(panel.config, dict) else {}
        transcript = panel.transcript if isinstance(panel.transcript, list) else []
        document_text = document_text_from_config(config)
        summary = str(result.get("summary") or panel.analysis or "").strip()
        html_path, slots_path, _payload = write_expertgranskning_artifacts(
            out_dir=ctx.out_dir,
            title=ctx.title,
            locale=ctx.locale,
            session_id=session_id,
            panel_id=panel.panel_id,
            document_text=document_text,
            summary=summary,
            transcript=transcript,
        )
    return ReportGenerateResult(
        html_path=html_path,
        slots_path=slots_path,
        timing={"total_seconds": 0.0},
    )
