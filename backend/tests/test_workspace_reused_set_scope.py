"""A persisted cross-run reference cannot widen workspace or frozen selection."""

from copy import deepcopy

import pytest

from app.database.models import EvidenceSet, ExecutionAttempt
from app.database.workspace_ids import company_workspace_id
from app.services.execution.errors import ExecutionScopeError
from app.services.execution.reuse_reference import REUSE_KEY
from app.services.execution.service import (
    add_evidence_items,
    create_attempt,
    create_evidence_set,
    create_run,
    freeze_evidence_set,
    require_frozen_evidence_for_attempt,
)
from app.services.research.models import research_evidence
from app.services.research.result_execution import may_attach_reused_set


def _context(workspace_id, *, manifest=None):
    context = {"case_id": "same-case"}
    if workspace_id is not None:
        context.update(workspace_id=workspace_id, readable_workspace_ids=[workspace_id])
    if manifest is not None:
        context["document_manifest"] = manifest
    return context


async def _persist_reference(factory, source_context, target_context):
    async with factory.begin() as session:
        source_run = await create_run(
            session, customer_id=1, module="dd", title="Source", context=source_context
        )
        source_attempt = await create_attempt(session, run_id=source_run.id, attempt_type="test")
        frozen = await create_evidence_set(
            session, run_id=source_run.id, created_from_attempt_id=source_attempt.id
        )
        await add_evidence_items(
            session,
            evidence_set_id=frozen.id,
            items=[
                research_evidence(
                    research_need_id="need",
                    source_type="customer_knowledge",
                    status="found",
                    source_id="private-contract",
                    excerpt="Confidential frozen source passage",
                )
            ],
        )
        await freeze_evidence_set(session, frozen.id)
        source_attempt.evidence_set_id = frozen.id
        source_attempt.status = "ready"
        target_run = await create_run(
            session, customer_id=1, module="dd", title="Target", context=target_context
        )
        target = await create_attempt(session, run_id=target_run.id, attempt_type="test")
        # This is the same durable reference written after completed-result
        # reuse. Both later execution and HTTP projection must recheck it.
        target.evidence_set_id = frozen.id
        target.status = "ready"
        target.input_snapshot = {REUSE_KEY: {"evidence_set_id": frozen.id}}
        return target.id, frozen.id


def _contexts(case, active, sibling):
    manifest = [
        {"source_object_id": "contract", "document_version_id": "version-1", "workspace_id": active}
    ]
    source = _context(active, manifest=manifest)
    target = deepcopy(source)
    company = company_workspace_id(1)
    if case == "sibling":
        target = _context(sibling, manifest=[{**manifest[0], "workspace_id": sibling}])
    elif case == "different-document":
        target["document_manifest"][0]["source_object_id"] = "other-contract"
    elif case == "different-version":
        target["document_manifest"][0]["document_version_id"] = "version-2"
    elif case == "company-default-source":
        source, target = _context(None, manifest=[]), _context(company, manifest=[])
    elif case == "company-default-target":
        source, target = _context(company, manifest=[]), _context(None, manifest=[])
    elif case == "unscoped-company":
        source = target = _context(None)
    elif case == "missing-source-manifest":
        source, target = _context(None), _context(company, manifest=[])
    elif case == "missing-scoped-manifests":
        source = target = _context(active)
    return source, target


@pytest.mark.parametrize(
    "case,allowed",
    [
        ("same-selection", True),
        ("sibling", False),
        ("different-document", False),
        ("different-version", False),
        ("company-default-source", True),
        ("company-default-target", True),
        ("unscoped-company", True),
        ("missing-source-manifest", False),
        ("missing-scoped-manifests", False),
    ],
)
async def test_persisted_cross_run_reference_checks_workspace_and_selection(
    client_db, user_token, case, allowed
):
    client, factory = client_db
    client.headers["Authorization"] = f"Bearer {user_token}"
    active, sibling = [
        (await client.post("/workspaces", json={"name": name})).json()["id"]
        for name in ("Client A", "Client B")
    ]
    source_context, target_context = _contexts(case, active, sibling)
    target_id, frozen_id = await _persist_reference(factory, source_context, target_context)
    async with factory() as session:
        target = await session.get(ExecutionAttempt, target_id)
        frozen = await session.get(EvidenceSet, frozen_id)
        assert await may_attach_reused_set(session, target, frozen) is allowed
        if allowed:
            assert (await require_frozen_evidence_for_attempt(session, target)).id == frozen_id
        else:
            with pytest.raises(ExecutionScopeError):
                await require_frozen_evidence_for_attempt(session, target)
    if case in ("company-default-source", "company-default-target"):
        # Normalization is checked at the attachment seam. These raw omitted
        # workspace declarations are rejected separately at the producer API.
        return
    response = await client.get(f"/execution/attempts/{target_id}/evidence")
    assert response.status_code == (200 if allowed else 403), response.text
    if allowed:
        assert response.json()["items"][0]["excerpt"] == "Confidential frozen source passage"
    else:
        assert "Confidential frozen source passage" not in response.text
