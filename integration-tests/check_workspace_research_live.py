"""End-to-end live workspace research through both chat entry points."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from workspace_live_runtime import LiveRuntime, REPO


async def _research_checks(runtime, client, fixture):
    from sqlalchemy import select
    from app.database.models import EvidenceSet, EvidenceSetItem, Job
    from app.services import jobs
    from app.services.workspace_research_answer import compose_research_answer

    observation = runtime.observation
    source = fixture["sources"]["client_a"]
    chat = fixture["client_a_chat"]
    question = "Vilket startdatum anges uttryckligen i klientens uppladdade avtal? Använd dokumentkällan och ange originalpassagen. Frågan gäller avtalets uppgifter, inte en rättslig bedömning."
    response = await client.post(
        f"/workspace-chats/{chat['id']}/research",
        json={"question": question, "source_object_ids": [source["id"]], "entrypoint": "modal"},
    )
    observation.assertion("modal_queues_real_research", response.status_code == 202)
    if response.status_code != 202:
        raise RuntimeError(f"Modal research returned {response.status_code}")
    job_id = response.json()["id"]
    print(json.dumps({"stage": "real_modal_research", "job_id": job_id}), flush=True)
    await jobs._run_job(job_id)
    async with runtime.factory() as session:
        job = await session.get(Job, job_id)
        result, status, error = dict(job.result or {}), job.status, job.error
        observation.assertion(
            "modal_research_succeeded", status == "succeeded", status=status, error=error
        )
        if status != "succeeded":
            raise RuntimeError("Live research failed; see report for job error")
        frozen = await session.get(EvidenceSet, result["evidence_set_id"])
        items = list(
            await session.scalars(
                select(EvidenceSetItem).where(EvidenceSetItem.evidence_set_id == frozen.id)
            )
        )
        originals = [
            item
            for item in items
            if item.status == "found" and item.provenance.get("source_object_id")
        ]
        observation.assertion(
            "research_freezes_canonical_originals",
            frozen.status == "frozen"
            and bool(originals)
            and all(
                item.provenance.get("source_object_id") == source["id"]
                and item.provenance.get("document_version_id") == source["document_version_id"]
                and bool(
                    item.provenance.get("text_unit_id")
                    or item.provenance.get("text_unit_ids")
                    or item.provenance.get("supporting_text_unit_ids")
                )
                for item in originals
            ),
        )
        observation.assertion(
            "research_answer_uses_client_a",
            source["start_date"] in result["answer"]
            and fixture["sources"]["client_b"]["start_date"] not in result["answer"],
        )
        observation.assertion(
            "frozen_citations_are_clickable",
            any(
                citation.get("source_object_id") == source["id"]
                and citation.get("document_version_id") == source["document_version_id"]
                and citation.get("text_unit_id")
                for citation in result["citations"]
            ),
        )
        observation.assertion(
            "citations_reference_original_sources_only",
            all(
                (citation.get("document_version_id") and citation.get("text_unit_id"))
                or str(citation.get("source_url") or "").startswith(("http://", "https://"))
                for citation in result["citations"]
            ),
        )
        attempt_id = result["attempt_id"]
    before = len(runtime.report["external_calls"])
    async with runtime.factory() as session:
        repeated = await compose_research_answer(session, job_id, attempt_id)
    observation.assertion(
        "persisted_answer_is_idempotent_without_new_llm",
        repeated == result and len(runtime.report["external_calls"]) == before,
    )
    runtime.report["modal_result"] = result
    await _tool_checks(runtime, client, fixture)


async def _tool_checks(runtime, client, fixture):
    from sqlalchemy import select
    from app.database.models import Job, KnowledgeQuestionRow
    from app.database.workspaces import WorkspaceChatMessage
    from app.services import jobs

    observation = runtime.observation
    source = fixture["sources"]["client_a"]
    chat = fixture["client_a_chat"]
    print(json.dumps({"stage": "real_chat_tool_request"}), flush=True)
    response = await client.post(
        f"/workspace-chats/{chat['id']}/messages",
        json={
            "content": "Gör research nu: Hur lång är uppsägningstiden i klientens uppladdade avtal? Använd dokumentkällan. Jag vill att du startar researchverktyget."
        },
    )
    observation.assertion("real_chat_tool_turn_succeeded", response.status_code == 200)
    queued = (await client.get(f"/workspace-chats/{chat['id']}/research")).json()
    tools = [job for job in queued if job["request"].get("entrypoint") == "tool"]
    observation.assertion("real_llm_invokes_research_tool", len(tools) == 1)
    if not tools:
        raise RuntimeError("Real chat model did not invoke research tool")
    tool_job = tools[0]
    observation.assertion(
        "tool_inherits_chat_and_freezes_only_readable_documents",
        tool_job["request"]["workspace_id"] == chat["workspace_id"]
        and {row["source_object_id"] for row in tool_job["request"]["document_manifest"]}
        == {source["id"], fixture["sources"]["company"]["id"]},
    )
    await jobs._run_job(tool_job["id"])
    async with runtime.factory() as session:
        completed = await session.get(Job, tool_job["id"])
        observation.assertion(
            "tool_uses_same_real_research_engine",
            completed.status == "succeeded"
            and bool((completed.result or {}).get("evidence_set_id")),
            status=completed.status,
            error=completed.error,
        )
        public_count = await session.scalar(
            select(KnowledgeQuestionRow.id)
            .where(KnowledgeQuestionRow.visibility == "public")
            .limit(1)
        )
        observation.assertion(
            "private_research_questions_never_promoted_global", public_count is None
        )
        messages = list(
            await session.scalars(
                select(WorkspaceChatMessage).where(
                    WorkspaceChatMessage.chat_id == chat["id"],
                    WorkspaceChatMessage.role == "assistant",
                    WorkspaceChatMessage.job_id.is_not(None),
                )
            )
        )
        observation.assertion(
            "research_result_appended_once_per_job",
            len(messages) == 2 and len({row.job_id for row in messages}) == 2,
        )
        runtime.report["tool_result"] = completed.result
    observation.save()


async def run(report_path: Path):
    from httpx import ASGITransport, AsyncClient

    runtime = LiveRuntime(report_path)
    try:
        await runtime.start()
        from check_workspace_ingest_live import run_checks

        async with AsyncClient(
            transport=ASGITransport(app=runtime.app),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {runtime.token()}"},
            timeout=300,
        ) as client:
            fixtures = await run_checks(
                runtime.factory, client, runtime.report, runtime.observation
            )
            runtime.observation.save()
            await _research_checks(runtime, client, fixtures)
        runtime.observation.assertion(
            "no_database_connection_held_over_real_external_calls",
            all(row["checked_out_at_start"] == 0 for row in runtime.report["external_calls"]),
        )
        passed = all(
            row["passed"]
            for row in runtime.report["assertions"] + runtime.report["document_ingest_checks"]
        )
        runtime.report["status"] = "passed" if passed else "failed_assertions"
    except Exception as exc:
        runtime.report.update(status="error", error_type=type(exc).__name__, error=str(exc)[:1500])
        raise
    finally:
        await runtime.cleanup()
    if runtime.report["status"] != "passed":
        raise RuntimeError("Workspace live checks failed; see the saved report")


if __name__ == "__main__":
    asyncio.run(run(REPO / "integration-tests/workspace-research-live.json"))
