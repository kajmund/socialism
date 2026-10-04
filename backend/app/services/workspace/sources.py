"""Real, scoped knowledge retrieval and stable version-bound citations."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, EvidenceSet, EvidenceSetItem, ExecutionAttempt, ExecutionRun, StoredObject, TextUnitRecord
from app.database.workspace_models import VoiceWorkspace, WorkspaceReference, WorkspaceResearch, WorkspaceSource
from app.services.workspace.service import fingerprint, new_id, require_reference, require_source
from app.services.workspace.research_links import sync_research_links
from app.services.research.workspace_grounding import passages_allowed
from app.services.research.models import ResearchContext
from app.services.knowledge.models import KnowledgeScope
from app.services.workspaces import resolve_readable_workspace_ids


def source_version(source: StoredObject) -> str:
    return fingerprint({"text": source.extracted_text, "key": source.object_key, "size": source.size_bytes})


async def citation(session: AsyncSession, workspace: VoiceWorkspace, *, kind: str, source_id: str,
                   version: str, anchor: dict, snapshot: dict) -> WorkspaceReference:
    if kind == "underlag":
        membership = await session.get(WorkspaceSource, (workspace.id, source_id))
        if membership is not None and membership.source_url:
            snapshot = {**snapshot, "source_url": membership.source_url}
    identity_fields = {"kind": kind, "source_id": source_id, "version": version, "anchor": anchor}
    if snapshot.get("selection_verified") is True:
        # A proved position must not reuse an older quote-only citation's identity.
        identity_fields["selection_verified"] = True
    identity = fingerprint(identity_fields)
    await session.execute(update(VoiceWorkspace).where(VoiceWorkspace.id == workspace.id).values(
        next_reference_number=VoiceWorkspace.next_reference_number))
    existing = (await session.execute(select(WorkspaceReference).where(
        WorkspaceReference.workspace_id == workspace.id, WorkspaceReference.identity_key == identity))).scalar_one_or_none()
    if existing:
        return existing
    number = (await session.execute(update(VoiceWorkspace).where(VoiceWorkspace.id == workspace.id).values(
        next_reference_number=VoiceWorkspace.next_reference_number + 1).returning(VoiceWorkspace.next_reference_number))).scalar_one() - 1
    reference = WorkspaceReference(id=new_id(), workspace_id=workspace.id, number=number, identity_key=identity,
                                   kind=kind, source_id=source_id, source_version=version, anchor=anchor, snapshot=snapshot)
    session.add(reference)
    await session.flush()
    return reference


def reference_out(ref: WorkspaceReference, *, stale: bool = False) -> dict:
    return {"reference_id": ref.id, "number": ref.number, "source_id": ref.source_id, "source_kind": ref.kind,
            "title": ref.snapshot.get("title"), "excerpt": ref.snapshot.get("excerpt"), "anchor": ref.anchor,
            "source_version": ref.source_version, "stale": stale, "snapshot": ref.snapshot,
            "file_url": f"/voice-workspaces/{ref.workspace_id}/sources/{ref.source_id}/file" if ref.kind == "underlag" and not stale else None}


async def read_reference(session: AsyncSession, workspace: VoiceWorkspace, reference_id: str) -> dict:
    ref = await require_reference(session, workspace, reference_id)
    stale = False
    if ref.kind == "underlag":
        source = await require_source(session, workspace, ref.source_id)
        stale = source_version(source) != ref.source_version
    elif ref.kind == "evidence":
        item = await session.get(EvidenceSetItem, ref.source_id)
        if item is None:
            raise HTTPException(status_code=404, detail="workspace_evidence_not_found")
        evidence_set = await session.get(EvidenceSet, item.evidence_set_id)
        run = await session.get(ExecutionRun, evidence_set.run_id) if evidence_set else None
        if evidence_set is None or evidence_set.status != "frozen" or run is None or run.customer_id != workspace.customer_id:
            raise HTTPException(status_code=404, detail="workspace_evidence_not_found")
        linked = await session.scalar(select(WorkspaceResearch.attempt_id).join(ExecutionAttempt,
            ExecutionAttempt.id == WorkspaceResearch.attempt_id).where(WorkspaceResearch.workspace_id == workspace.id,
            ExecutionAttempt.run_id == run.id, ExecutionAttempt.evidence_set_id == evidence_set.id))
        if linked is None:
            await sync_research_links(session, workspace)
            linked = await session.scalar(select(WorkspaceResearch.attempt_id).join(ExecutionAttempt,
                ExecutionAttempt.id == WorkspaceResearch.attempt_id).where(WorkspaceResearch.workspace_id == workspace.id,
                ExecutionAttempt.run_id == run.id, ExecutionAttempt.evidence_set_id == evidence_set.id))
        if linked is None:
            raise HTTPException(status_code=404, detail="workspace_evidence_not_found")
        stale = item.content_hash != ref.source_version
    elif ref.kind == "graph":
        stale = await _graph_reference_stale(session, workspace, ref)
    else:
        raise HTTPException(status_code=404, detail="workspace_reference_not_found")
    return reference_out(ref, stale=stale)


async def evidence_citation(session: AsyncSession, workspace: VoiceWorkspace, item: EvidenceSetItem, *, visibility: str = "tenant") -> WorkspaceReference:
    return await citation(session, workspace, kind="evidence", source_id=item.id, version=item.content_hash,
        anchor={"anchor_type": "text", "locator": item.locator, "exact_text": item.excerpt, "rects": []},
        snapshot={"title": item.title, "excerpt": item.excerpt, "source_url": item.source_url, "source_type": item.source_type,
                  "evidence_set_id": item.evidence_set_id, "provenance": item.provenance, "visibility": visibility})


async def search_research(session: AsyncSession, workspace: VoiceWorkspace, query: str, limit: int, *, attempt_ids: list[str]) -> dict:
    await sync_research_links(session, workspace)
    refs, gaps = [], []
    for attempt_id in attempt_ids:
        if await session.get(WorkspaceResearch, (workspace.id, attempt_id)) is None:
            raise HTTPException(status_code=404, detail="workspace_research_not_found")
        attempt = await session.get(ExecutionAttempt, attempt_id)
        evidence_set = await session.get(EvidenceSet, attempt.evidence_set_id) if attempt and attempt.evidence_set_id else None
        if evidence_set is None or evidence_set.status != "frozen":
            gaps.append({"attempt_id": attempt_id, "status": attempt.status if attempt else "missing"})
            continue
        terms = [term for term in query.casefold().split() if term]
        items = list((await session.execute(select(EvidenceSetItem).where(EvidenceSetItem.evidence_set_id == evidence_set.id,
            EvidenceSetItem.status == "found").order_by(EvidenceSetItem.ordinal))).scalars())
        for item in items:
            if terms and not any(term in f"{item.title or ''} {item.excerpt or ''}".casefold() for term in terms):
                continue
            refs.append(await evidence_citation(session, workspace, item))
            if len(refs) >= limit:
                return {"items": [reference_out(ref) for ref in refs], "gaps": gaps}
    return {"items": [reference_out(ref) for ref in refs], "gaps": gaps}


async def _graph_reference_stale(session: AsyncSession, workspace: VoiceWorkspace, ref: WorkspaceReference) -> bool:
    version = await session.get(DocumentVersionRecord, ref.source_id)
    document = await session.get(CanonicalDocumentRecord, version.document_id) if version else None
    scopes = {"shared", f"customer:{workspace.customer_id}"}
    if version is None or document is None or version.scope_key not in scopes or document.scope_key != version.scope_key:
        raise HTTPException(status_code=404, detail="workspace_graph_source_not_found")
    unit_ids = ref.snapshot.get("supporting_text_unit_ids", [])
    units = list((await session.scalars(select(TextUnitRecord).where(TextUnitRecord.id.in_(unit_ids)))).all())
    if not unit_ids or len(units) != len(unit_ids) or any(unit.document_version_id != version.id or unit.scope_key != version.scope_key for unit in units):
        raise HTTPException(status_code=409, detail="workspace_graph_grounding_invalid")
    parents = await resolve_readable_workspace_ids(session, customer_id=workspace.customer_id,
        user_id=workspace.owner_user_id, workspace_id=workspace.workspace_id)
    scope = KnowledgeScope(customer_id=workspace.customer_id, workspace_id=workspace.workspace_id,
                           readable_workspace_ids=tuple(parents))
    if not await passages_allowed(session, units, ResearchContext(scope=scope)):
        raise HTTPException(status_code=404, detail="workspace_graph_source_not_found")
    return version.content_hash != ref.source_version or version.superseded_at is not None
