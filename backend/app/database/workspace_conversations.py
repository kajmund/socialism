"""Private provider connections and their durable links to local expert history."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class WorkspaceConversationSession(Base):
    __tablename__ = "workspace_conversation_sessions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "generation", name="uq_workspace_conversation_generation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("kunder.id", ondelete="RESTRICT"), index=True)
    expert_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(8))
    language: Mapped[str] = mapped_column(String(8), default="sv")
    generation: Mapped[int] = mapped_column(Integer)
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prompt_version: Mapped[str] = mapped_column(String(64))
    agent_version: Mapped[str] = mapped_column(String(128))
    agent_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceConversationEvent(Base):
    __tablename__ = "workspace_conversation_events"
    __table_args__ = (
        UniqueConstraint("session_id", "event_key", name="uq_workspace_conversation_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("workspace_conversation_sessions.id", ondelete="CASCADE"), index=True)
    event_key: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16))
    message_id: Mapped[int | None] = mapped_column(ForeignKey("persona_messages.id", ondelete="SET NULL"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceAgentDeployment(Base):
    __tablename__ = "workspace_agent_deployments"
    __table_args__ = (
        UniqueConstraint("customer_id", "language", "expert_id", "prompt_version", name="uq_workspace_agent_snapshot"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    customer_id: Mapped[int] = mapped_column(ForeignKey("kunder.id", ondelete="RESTRICT"), index=True)
    language: Mapped[str] = mapped_column(String(8))
    expert_id: Mapped[str] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True)
    prompt_version: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[str] = mapped_column(String(128))
    agent_version: Mapped[str] = mapped_column(String(128))
    tool_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    procedure_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
