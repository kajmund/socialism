"""Dispatch research and ingest jobs without holding the job-state transaction."""


async def run_research_job(job_id: str, kind: str) -> None:
    from app.services.jobs import _succeed, job_session_factory

    if kind == "workspace_research":
        from app.services.workspace_research_job import run_workspace_research_job as runner
    elif kind == "expert_chat_research":
        from app.services.expert_chat_research import run_expert_chat_research_job as runner
    else:
        from app.services.document_ingest_job import run_document_ingest_job as runner
    factory = job_session_factory()
    result = await runner(factory, job_id=job_id)
    async with factory() as session:
        await _succeed(session, job_id, result)
