"""Rättsunderlag report generator — shared rattsutredning renderer."""

from __future__ import annotations

from app.database.models import Job
from app.modules.report_binding import ReportGenerateContext, ReportGenerateResult
from app.services.rattsunderlag import REPORT_MODE, SOURCE_TYPE
from app.services.rattsunderlag.schemas import RattsunderlagResult
from app.services.report.rattsutredning import write_rattsutredning_artifacts


async def generate_rattsunderlag_module_report(
    ctx: ReportGenerateContext,
) -> ReportGenerateResult:
    sources = ctx.sources
    if len(sources) != 1 or sources[0].get("type") != SOURCE_TYPE:
        raise ValueError("Rättsunderlag report requires exactly one rattsunderlag source")
    job_id = str(sources[0].get("session_id") or "").strip()
    if not job_id:
        raise ValueError("rattsunderlag source requires session_id")
    async with ctx.session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Research job not found: {job_id}")
        raw = job.result if isinstance(job.result, dict) else None
        payload = raw.get("result") if raw else None
        if not isinstance(payload, dict):
            raise ValueError(f"Research job {job_id} has no result payload")
        result = RattsunderlagResult.model_validate(payload)
    html_path, slots_path, _doc = write_rattsutredning_artifacts(
        result.as_payload(),
        out_dir=ctx.out_dir,
        title=ctx.title,
        locale=ctx.locale,
        source_type=SOURCE_TYPE,
        session_id=job_id,
        mode=ctx.mode or REPORT_MODE,
    )
    return ReportGenerateResult(
        html_path=html_path,
        slots_path=slots_path,
        timing={"total_seconds": 0.0},
    )
