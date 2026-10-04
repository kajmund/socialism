"""Authenticated downloads of exact workspace document revisions."""

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.models import UserAccount
from app.database.session import get_session
from app.database.workspace_models import WorkspaceArtifactRevision, WorkspaceReference
from app.services.underlag_pdf import UnderlagPdfConversionError, convert_docx_to_pdf_async
from app.services.workspace.service import require_artifact, require_workspace
from app.services.workspace_export import export_revision_docx

router = APIRouter(prefix="/voice-workspaces", tags=["workspaces"])


@router.get("/{workspace_id}/artifacts/{artifact_id}/exports/{format}")
async def export_document(
    workspace_id: str,
    artifact_id: str,
    format: Literal["docx", "pdf"],
    *,
    revision: int = Query(ge=1),
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> Response:
    workspace = await require_workspace(session, workspace_id, user)
    artifact = await require_artifact(session, workspace, artifact_id)
    if artifact.kind != "document":
        raise HTTPException(status_code=422, detail="only_documents_can_be_exported")
    snapshot = await session.get(WorkspaceArtifactRevision, (artifact_id, revision))
    if snapshot is None:
        raise HTTPException(status_code=404, detail="artifact_revision_not_found")
    references = list((await session.execute(select(WorkspaceReference).where(WorkspaceReference.workspace_id == workspace.id))).scalars())
    data = export_revision_docx(snapshot, references)
    name = quote(f"{snapshot.title}-r{revision}.{format}", safe="")
    await session.rollback()
    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if format == "pdf":
        try:
            data = await convert_docx_to_pdf_async(data, filename=f"{artifact_id}-r{revision}.docx")
        except UnderlagPdfConversionError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        media_type = "application/pdf"
    return Response(data, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename=\"document-r{revision}.{format}\"; filename*=UTF-8''{name}",
        "Cache-Control": "private, no-store",
        "X-Artifact-Revision": str(revision),
    })
