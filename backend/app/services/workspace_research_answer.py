"""Compose a workspace reply exclusively from persisted frozen evidence."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job
from app.database.workspaces import Workspace, WorkspaceChatMessage
from app.llm import complete_text
from app.services.execution.evidence_render import render_frozen_evidence
from app.services.execution.service import (
    get_attempt,
    list_evidence_items,
    require_frozen_evidence_for_attempt,
)
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts


async def compose_research_answer(session: AsyncSession, job_id: str, attempt_id: str) -> dict:
    job = await session.get(Job, job_id)
    existing = await session.scalar(
        select(WorkspaceChatMessage).where(
            WorkspaceChatMessage.job_id == job_id,
            WorkspaceChatMessage.role == "assistant",
        )
    )
    if existing is not None:
        saved = dict(job.result or {})
        if saved.get("attempt_id") != attempt_id or saved.get("answer") != existing.content:
            raise ValueError("Persisted research reply and job result disagree")
        await session.rollback()
        return saved
    attempt = await get_attempt(session, attempt_id)
    frozen = await require_frozen_evidence_for_attempt(session, attempt)
    items = await list_evidence_items(session, frozen.id)
    rendered = render_frozen_evidence(_answer_items(items))
    prompts = await require_active_prompts(
        session, customer_id=job.customer_id, module=job.request["module"], language="sv"
    )
    workspace = await session.get(Workspace, job.request["workspace_id"])
    prompt = render_prompt(
        prompts,
        "chat.workspace.answer",
        question=job.request["question"],
        evidence=rendered.prompt_body
        + "\n\nKällornas ägande:\n"
        + _source_labels(items, rendered.refs, workspace),
        workspace_name=workspace.name,
    )
    citations = _citations(items, rendered.refs)
    result = {
        "run_id": attempt.run_id,
        "attempt_id": attempt.id,
        "evidence_set_id": frozen.id,
        "citations": citations,
    }
    chat_id = job.request["chat_id"]
    await session.rollback()
    answer = await complete_text(
        [{"role": "user", "content": prompt}], prompt_key="chat.workspace.answer"
    )
    if not answer or not answer.strip():
        raise ValueError("Research answer was empty")
    if set(re.findall(r"(?:\[|【)(E\d+)(?:\]|】)", answer)) - rendered.refs.keys():
        raise ValueError("Research answer cited evidence outside its frozen set")
    result["answer"] = answer.strip()
    existing = await session.scalar(
        select(WorkspaceChatMessage.id).where(
            WorkspaceChatMessage.chat_id == chat_id,
            WorkspaceChatMessage.job_id == job_id,
            WorkspaceChatMessage.role == "assistant",
        )
    )
    if existing is None:
        session.add(
            WorkspaceChatMessage(
                chat_id=chat_id, role="assistant", content=answer.strip(), job_id=job_id
            )
        )
    persisted_job = await session.get(Job, job_id)
    persisted_job.result = result
    await session.commit()
    return result


def _answer_items(items) -> list:
    """Intermediate answers aid research but are not independent source evidence."""
    output = []
    for item in items:
        metadata = item.provenance or {}
        units = (
            metadata.get("text_unit_id")
            or metadata.get("text_unit_ids")
            or metadata.get("supporting_text_unit_ids")
        )
        original = bool(metadata.get("document_version_id") and units)
        external = bool(item.source_url and item.source_url.startswith(("http://", "https://")))
        if item.status != "found" or (item.source_type != "derived" and (original or external)):
            output.append(item)
    return output


def _citations(items, refs) -> list[dict]:
    by_id = {item.id: item for item in items}
    output = []
    for label, ref in refs.items():
        item = by_id[ref.item_id]
        metadata = item.provenance or {}
        units = metadata.get("text_unit_ids") or metadata.get("supporting_text_unit_ids") or []
        output.append(
            {
                "label": label,
                "source_object_id": metadata.get("source_object_id"),
                "document_version_id": metadata.get("document_version_id"),
                "text_unit_id": metadata.get("text_unit_id") or (units[0] if units else None),
                "locator": item.locator,
                "excerpt": item.excerpt,
                "source_url": item.source_url,
                "workspace_id": metadata.get("workspace_id"),
            }
        )
    return output


def _source_labels(items, refs, workspace) -> str:
    by_id = {item.id: item for item in items}
    lines = []
    for label, ref in refs.items():
        item = by_id[ref.item_id]
        metadata = item.provenance or {}
        if metadata.get("workspace_id") == workspace.id and workspace.kind == "client":
            owner = "Klientens dokument"
        elif metadata.get("workspace_id") or metadata.get("source_object_id"):
            owner = "Företagets privata kunskap"
        elif metadata.get("scope_type") == "shared":
            owner = "Global kunskap"
        else:
            owner = "Företagets privata kunskap"
        lines.append(f"[{label}] {owner}: {item.title or item.source_type}")
    return "\n".join(lines)
