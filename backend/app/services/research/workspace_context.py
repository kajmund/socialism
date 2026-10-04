"""Authoritative execution scope, including frozen workspace document selection."""

from app.database.models import ExecutionRun
from app.services.knowledge.models import KnowledgeScope
from app.services.research.models import ResearchContext


def research_context_from_run(run: ExecutionRun) -> ResearchContext:
    raw = run.context if isinstance(run.context, dict) else {}
    workspace_id = raw.get("workspace_id")
    if workspace_id is None and any(
        key in raw for key in ("document_manifest", "readable_workspace_ids")
    ):
        raise ValueError("A frozen document manifest requires a resolved workspace")
    fields = {}
    if workspace_id is not None:
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise ValueError("Invalid research workspace")
        manifest = raw.get("document_manifest")
        readable = raw.get("readable_workspace_ids")
        if not isinstance(manifest, list) or not isinstance(readable, list):
            raise ValueError("Workspace research requires its frozen document manifest")
        if workspace_id not in readable or any(not isinstance(value, str) for value in readable):
            raise ValueError("Invalid readable workspace scope")
        if any(
            not isinstance(row, dict)
            or not all(
                isinstance(row.get(key), str)
                for key in ("source_object_id", "document_version_id", "workspace_id")
            )
            for row in manifest
        ):
            raise ValueError("Invalid frozen document manifest")
        if any(row["workspace_id"] not in readable for row in manifest):
            raise ValueError("Document manifest crossed a workspace boundary")
        fields = {
            "workspace_id": workspace_id,
            "readable_workspace_ids": tuple(readable),
            "allowed_source_object_ids": tuple(row["source_object_id"] for row in manifest),
            "allowed_document_version_ids": tuple(row["document_version_id"] for row in manifest),
        }
    return ResearchContext(
        scope=KnowledgeScope(
            customer_id=run.customer_id,
            case_id=str(raw["case_id"]).strip() or None if raw.get("case_id") else None,
            module=str(raw.get("knowledge_module") or run.module).strip(),
            **fields,
        )
    )
