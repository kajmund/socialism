"""DD module report generator — owned by the dd ModuleManifest ReportBinding."""

from __future__ import annotations

from app.modules.report_binding import ReportGenerateContext, ReportGenerateResult
from app.services.dd.sub_questions import SubQuestionRef
from app.services.panel.result import dd_panel_result_from_stored
from app.services.panel.sessions import get_panel_session
from app.services.panel.sub_questions_store import get_sub_questions
from app.services.report.dd_report import generate_dd_report_html


async def generate_dd_module_report(ctx: ReportGenerateContext) -> ReportGenerateResult:
    # Late import: module_defaults → MODULE_REGISTRY, and registry wires this function.
    from app.services.panel.module_defaults import ensure_module_panel_defaults

    sources = ctx.sources
    if len(sources) != 1 or sources[0].get("type") != "dd_session":
        raise ValueError("DD report requires exactly one dd_session source")
    src = sources[0]
    session_id = str(src["session_id"])
    candidate_id = str(src["candidate_id"])
    async with ctx.session_factory() as session:
        panel = await get_panel_session(session, session_id)
        if panel is None:
            raise ValueError(f"Panel session not found: {session_id}")
        if panel.protocol != "dd_panel":
            raise ValueError("Panel session is not dd_panel")
        if panel.status != "succeeded":
            raise ValueError("Panel session has not succeeded")
        if not isinstance(panel.result, dict):
            raise ValueError("Panel session has no result")
        result = dd_panel_result_from_stored(panel.result)
        await ensure_module_panel_defaults(session)
        sq_rows = await get_sub_questions(session, "dd")
        sub_questions = [SubQuestionRef(id=row.key, label=row.label) for row in sq_rows]
    html_path, slots_path, _slots, _dd = await generate_dd_report_html(
        result,
        session_id=session_id,
        candidate_id=candidate_id,
        out_dir=ctx.out_dir,
        title=ctx.title,
        locale=ctx.locale,
        sub_questions=sub_questions,
    )
    return ReportGenerateResult(
        html_path=html_path,
        slots_path=slots_path,
        timing={"total_seconds": 0.0},
    )
