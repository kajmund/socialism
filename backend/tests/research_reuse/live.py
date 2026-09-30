"""Real-service step runner. CI calls the same probes with mocked boundaries."""

from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database.sqlite import register_sqlite_pragmas
from app.llm.lagen_nu_selector import LlmLagenNuSelector
from app.llm.legal_research import LlmLegalInterpreter
from app.llm.runtime_override import current_runtime
from app.services.execution import get_attempt, get_run, list_runtime_needs, runtime_need_from_row
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.lagen_nu.mcp_client import OfficialLagenNuMcpClient
from app.services.lagen_nu.research_source import LagenNuResearchSource
from app.services.llm_runtime_settings import get_default_configuration, load_runtime_settings
from app.services.prompt_store import require_active_prompts
from app.services.research.composition import standard_available_source_types
from app.services.research.execution import research_context_from_run
from app.services.research.models import ResearchNeed
from tests.research_reuse import probes
from tests.research_reuse.snapshots import (
    ASSESSMENT,
    EVIDENCE,
    GAPS,
    TimedStep,
    digest,
    read,
    save,
    summary,
)


async def workload(factory, attempt_id: str, need_id: str | None):
    async with factory() as session:
        attempt = await get_attempt(session, attempt_id)
        run = await get_run(session, attempt.run_id)
        context = replace(research_context_from_run(run), attempt_id=attempt.id)
        if need_id:
            needs = await list_runtime_needs(session, attempt.id)
            selected = next((row for row in needs if row.research_need_id == need_id), None)
            if selected is None:
                raise ValueError("The selected need does not belong to this attempt")
            need = runtime_need_from_row(selected).as_need()
        else:
            objective = (attempt.research_objective_snapshot or {}).get("objective")
            if not objective:
                raise ValueError("The attempt has no persisted research objective")
            from app.database.models import KnowledgeQuestionRow
            from app.services.research.knowledge_question import identity_from_text
            from sqlalchemy import select

            main_rows = await list_runtime_needs(session, attempt.id)
            canonical_id = next(
                (
                    row.knowledge_question_id
                    for row in main_rows
                    if row.research_need_id == "research-main"
                ),
                "",
            )
            if not canonical_id:
                canonical_id = (
                    await session.scalar(
                        select(KnowledgeQuestionRow.id).where(
                            KnowledgeQuestionRow.scope_key == f"customer:{run.customer_id}",
                            KnowledgeQuestionRow.identity_key
                            == identity_from_text(objective).identity_key,
                        )
                    )
                    or ""
                )
            need = ResearchNeed(
                id="main",
                knowledge_question_id=canonical_id,
                question=objective,
                why_needed="Main-question reuse probe",
                source_types=list(standard_available_source_types()),
            )
        if await get_default_configuration(session) is None:
            raise ValueError("A configured default LLM configuration is required")
        await load_runtime_settings(session)
        prompts = await require_active_prompts(
            session,
            customer_id=run.customer_id,
            module=run.module,
            language="sv",
        )
        runtime = current_runtime()
        metadata = {
            "provider": runtime.provider,
            "model": runtime.model,
            "prompt_digest": digest(prompts),
            "embedding_model": settings.embedding_model,
        }
    return need, context, metadata


async def fetch_gap(factory, row, context):
    if len(row.source_types) != 1:
        raise ValueError("The selected source probe must request exactly one source type")
    client = OfficialLagenNuMcpClient()
    try:
        source = LagenNuResearchSource(
            source_type=row.source_types[0],
            client=client,
            selector=LlmLagenNuSelector(session_factory=factory),
            interpreter=LlmLegalInterpreter(session_factory=factory),
        )
        # Source-only probe: no provider ingestion, vector upsert or attempt mutation.
        return await source.research(row.as_need(), context)
    finally:
        await client.aclose()


async def run_step(stage, *, factory, target, paths, timings, fetch_index=None):
    need, context = target["need"], target["context"]
    identity = target["identity"]
    if stage == 1:
        items = await probes.lookup(
            factory, need, context, OpenAIEmbeddingProvider.from_settings(), timings=timings
        )
        payload = EVIDENCE.dump_python(items, mode="json")
        save(paths[1], target=identity, stage=1, payload=payload)
        return {"graph_evidence_count": len(items)}
    if stage == 4:
        result = await probes.capture(factory, identity["attempt_id"])
        save(paths[4], target=identity, stage=4, payload=result)
        return {"contract_passed": result["contract_passed"], "writes": result["writes"]}
    first = read(paths[1], target=identity, stage=1)
    items = EVIDENCE.validate_python(first["payload"])
    parent = digest(first["payload"])
    if stage == 2:
        assessment = await probes.assess(factory, need, items, context, timings=timings)
        save(
            paths[2],
            target=identity,
            stage=2,
            payload=ASSESSMENT.dump_python(assessment, mode="json"),
            parent=parent,
        )
        return {"assessment": assessment.result, "gap_count": len(assessment.gaps)}
    second = read(paths[2], target=identity, stage=2, parent=parent)
    assessment = ASSESSMENT.validate_python(second["payload"])
    rows = await probes.gaps(factory, need, items, assessment, context=context, timings=timings)
    payload = {"gaps": GAPS.dump_python(rows, mode="json")}
    source_errors = 0
    if fetch_index is not None:
        if not 1 <= fetch_index <= len(rows):
            raise ValueError("--fetch-gap must select an existing gap (one-based)")
        started = perf_counter()
        retrieved = await fetch_gap(factory, rows[fetch_index - 1], context)
        timings["source_retrieval"] = perf_counter() - started
        payload["source_evidence"] = EVIDENCE.dump_python(retrieved, mode="json")
        source_errors = sum(item.status == "error" for item in retrieved)
    save(paths[3], target=identity, stage=3, payload=payload, parent=digest(second["payload"]))
    return {
        "gap_count": len(rows),
        "external_source_probe": fetch_index is not None,
        "source_errors": source_errors,
    }


async def run(args) -> dict:
    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0, pool_timeout=5)
    register_sqlite_pragmas(engine, settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    measurements = []
    output = {"mode": "live", "attempt_id": args.attempt_id, "measurements": measurements}
    directory = Path(
        args.workspace or f"data/research_reuse_lab/{args.attempt_id}/{args.need_id or 'main'}"
    )
    paths = {stage: directory / f"step_{stage}.json" for stage in range(1, 5)}
    try:
        need, context, metadata = await workload(factory, args.attempt_id, args.need_id)
        identity = {"attempt_id": args.attempt_id, "need": asdict(need), "context": asdict(context)}
        target = {"need": need, "context": context, "identity": identity}
        output.update({"question": need.question, "configuration": metadata})
        stages = range(1, 5) if args.step == "all" else [int(args.step)]
        for _iteration in range(args.repeat):
            for stage in stages:
                with TimedStep(stage, measurements) as timer:
                    result = await run_step(
                        stage,
                        factory=factory,
                        target=target,
                        paths=paths,
                        timings=timer.parts,
                        fetch_index=args.fetch_gap,
                    )
                measurements[-1]["result"] = result
                if result.get("source_errors"):
                    measurements[-1].update(status="error", error_type="SourceEvidenceError")
                if result.get("contract_passed") is False:
                    measurements[-1]["status"] = "contract_failed"
    finally:
        await engine.dispose()
        output["summary"] = summary(measurements)
        directory.mkdir(parents=True, exist_ok=True)
        import json

        (directory / "timings.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return output
