"""Owner-scoped workspaces, stable citations and immutable artifact revisions."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class VoiceWorkspace(Base):
    __tablename__ = "voice_workspaces"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "creation_key", name="uq_workspace_creation_key"),
        UniqueConstraint("chat_id", name="uq_voice_workspace_chat"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("workspace_chats.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("kunder.id", ondelete="RESTRICT"), index=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True)
    creation_key: Mapped[str] = mapped_column(String(160))
    creation_payload_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    module: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_reference_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceSource(Base):
    __tablename__ = "workspace_sources"
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("voice_workspaces.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("stored_objects.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceExpertThread(Base):
    __tablename__ = "workspace_expert_threads"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("voice_workspaces.id", ondelete="CASCADE"), primary_key=True)
    expert_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceResearch(Base):
    __tablename__ = "workspace_research"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("voice_workspaces.id", ondelete="CASCADE"), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("execution_attempts.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceReference(Base):
    __tablename__ = "workspace_references"
    __table_args__ = (
        UniqueConstraint("workspace_id", "identity_key", name="uq_workspace_reference_identity"),
        UniqueConstraint("workspace_id", "number", name="uq_workspace_reference_number"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("voice_workspaces.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    identity_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[str] = mapped_column(String(512))
    source_version: Mapped[str] = mapped_column(String(64))
    anchor: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceArtifact(Base):
    __tablename__ = "workspace_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("voice_workspaces.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkspaceArtifactRevision(Base):
    __tablename__ = "workspace_artifact_revisions"
    artifact_id: Mapped[str] = mapped_column(ForeignKey("workspace_artifacts.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceOperation(Base):
    __tablename__ = "workspace_operations"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key", name="uq_workspace_operation_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("voice_workspaces.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    payload_hash: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="accepted")
    context_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
