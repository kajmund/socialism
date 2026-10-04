"""Verify a question's captured selection without rewriting canvas state."""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.database.transaction_state import has_pending_writes
from app.database.workspace_conversations import WorkspaceConversationSession
from app.database.workspace_models import VoiceWorkspace
from app.schemas.workspace import WorkspaceState
from app.services.workspace.selection_verification import (
    PDFSelectionProof, SelectionInput, capture_selection_input, materialize_pdf_selection,
    prove_pdf_selection, refresh_selection_source,
)
from app.services.workspace_conversations import require_conversation


@dataclass(frozen=True)
class PreparedUserSelection:
    provider: WorkspaceConversationSession
    workspace: VoiceWorkspace
    state: WorkspaceState
    original: SelectionInput | None
    proof: PDFSelectionProof | None


async def _locked_provider(session: AsyncSession, *, workspace_id: str, provider_id: str,
                           actor_id: str) -> tuple[VoiceWorkspace, WorkspaceConversationSession]:
    actor = await session.get(UserAccount, actor_id, populate_existing=True)
    if actor is None:
        raise HTTPException(status_code=404, detail="workspace_conversation_not_found")
    # A no-op UPDATE also serializes SQLite, where SELECT FOR UPDATE does not.
    # Canvas precedes provider, matching bootstrap and citation lock order.
    locked = await session.scalar(update(VoiceWorkspace).where(VoiceWorkspace.id == workspace_id).values(
        next_reference_number=VoiceWorkspace.next_reference_number).returning(VoiceWorkspace.id))
    if locked is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    workspace = await session.get(VoiceWorkspace, workspace_id, populate_existing=True)
    provider = await require_conversation(session, session_id=provider_id, workspace_id=workspace_id, user=actor)
    return workspace, provider


async def prepare_user_selection(session: AsyncSession, provider: WorkspaceConversationSession,
                                 request) -> PreparedUserSelection:
    if has_pending_writes(session):
        raise RuntimeError("Question selection verification requires a clean transaction")
    provider_id, workspace_id, actor_id = provider.id, provider.workspace_id, provider.user_id
    workspace = await session.get(VoiceWorkspace, workspace_id)
    state = WorkspaceState.model_validate(
        request.context_snapshot if request.context_snapshot is not None else workspace.state).model_copy(deep=True)
    if state.expert_id != provider.expert_id:
        raise HTTPException(status_code=409, detail="workspace_conversation_expert_changed")
    actor = await session.get(UserAccount, actor_id)
    original = await capture_selection_input(session, workspace, actor, state)
    proof = await prove_pdf_selection(session, workspace, actor, state, require_file_hash=True)
    # Cached proofs and non-PDF selections must release the initial provider lock too.
    await session.rollback()
    workspace, provider = await _locked_provider(session, workspace_id=workspace_id,
        provider_id=provider_id, actor_id=actor_id)
    if state.expert_id != provider.expert_id:
        raise HTTPException(status_code=409, detail="workspace_conversation_expert_changed")
    return PreparedUserSelection(provider, workspace, state, original, proof)


async def materialize_user_selection(session: AsyncSession, prepared: PreparedUserSelection) -> WorkspaceState:
    if prepared.original is not None:
        await refresh_selection_source(session, prepared.original)
        prepared.state.selection.source_version = prepared.original.version
    if prepared.proof is not None:
        await materialize_pdf_selection(session, prepared.state, prepared.proof)
    return prepared.state
