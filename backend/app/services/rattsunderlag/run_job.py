"""Background worker for rattsunderlag_research jobs."""

from __future__ import annotations

import secrets
from pathlib import Path

from app.database.models import Job, Report
from app.modules.report_binding import ReportGenerateContext
from app.serializers import utcnow
from app.services.rattsunderlag import JOB_KIND, MODULE_ID, REPORT_MODE, SOURCE_TYPE
from app.services.rattsunderlag.module_report import generate_rattsunderlag_module_report
from app.services.rattsunderlag.persist import save_rattsunderlag_underlag
from app.services.rattsunderlag.research import run_rattsunderlag_research
from app.services.rattsunderlag.schemas import RattsunderlagResearchJobRequest
from app.services.report import ARTIFACT_ROOT
from app.services.report.locale import normalize_locale
from app.services.report_realtime import publish_report
from app.services.stored_objects import store_report_artifacts


async def run_rattsunderlag_research_job(job_id: str) -> None:
    # Circular: jobs.py owns the worker helpers and imports this runner.
    from app.services.jobs import _fail, _succeed, job_session_factory

    factory = job_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        payload = RattsunderlagResearchJobRequest.model_validate(job.request or {})
        locale = normalize_locale(payload.locale)
        result = await run_rattsunderlag_research(
            fraga=payload.fraga,
            customer_id=payload.customer_id,
            language=locale,
            session=session,
        )
        underlag = await save_rattsunderlag_underlag(
            session,
            customer_id=payload.customer_id,
            owner_user_id=payload.owner_user_id,
            payload=result.as_payload(),
            locale=locale,
            filename=f"rattsunderlag-{job_id[-8:]}.md",
        )
        report = Report(
            id=f"rpt_{secrets.token_hex(8)}",
            customer_id=payload.customer_id,
            status="running",
            title=payload.fraga[:255],
            locale=locale,
            mode=REPORT_MODE,
            sources=[{"type": SOURCE_TYPE, "session_id": job_id}],
            job_id=job_id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(report)
        job.result = {
            "result": result.model_dump(),
            "underlag_id": underlag.id,
            "report_id": report.id,
        }
        await session.commit()
        await session.refresh(report)
        report_id = report.id
        await publish_report(report)

    try:
        out_dir = Path(ARTIFACT_ROOT) / report_id
        generated = await generate_rattsunderlag_module_report(
            ReportGenerateContext(
                report_id=report_id,
                title=payload.fraga[:255],
                locale=locale,
                sources=[{"type": SOURCE_TYPE, "session_id": job_id}],
                mode=REPORT_MODE,
                out_dir=out_dir,
                session_factory=factory,
            )
        )
        async with factory() as session:
            report = await session.get(Report, report_id)
            if report is None:
                raise ValueError(f"Report disappeared: {report_id}")
            await store_report_artifacts(
                session,
                report,
                out_dir,
                module=MODULE_ID,
            )
            report.status = "succeeded"
            report.html_path = str(generated.html_path)
            report.slots_path = str(generated.slots_path)
            report.error = None
            report.finished_at = utcnow()
            report.updated_at = utcnow()
            await session.commit()
            await publish_report(report)
            await _succeed(
                session,
                job_id,
                {
                    "result": result.model_dump(),
                    "underlag_id": underlag.id,
                    "report_id": report_id,
                    "html_path": str(generated.html_path),
                    "sourcing_status": result.sourcing_status,
                },
            )
    except Exception as exc:
        async with factory() as session:
            report = await session.get(Report, report_id)
            if report is not None:
                report.status = "failed"
                report.error = (str(exc) or exc.__class__.__name__)[:2000]
                report.finished_at = utcnow()
                report.updated_at = utcnow()
                await session.commit()
                await publish_report(report)
            await _fail(session, job_id, str(exc) or exc.__class__.__name__)
