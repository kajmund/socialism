"""Durable batch ingest rows. Each file is its own document job."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class DocumentIngestBatch(Base):
    __tablename__ = "document_ingest_batches"
    __table_args__ = (
        Index("ix_document_ingest_batches_workspace", "voice_workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("kunder.id", ondelete="RESTRICT"), nullable=False)
    voice_workspace_id: Mapped[str] = mapped_column(
        ForeignKey("voice_workspaces.id", ondelete="CASCADE"), nullable=False,
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class DocumentIngestBatchItem(Base):
    __tablename__ = "document_ingest_batch_items"
    __table_args__ = (
        Index("ix_document_ingest_batch_items_batch", "batch_id"),
        Index("ix_document_ingest_batch_items_job", "job_id"),
        Index("ix_document_ingest_batch_items_work", "graph_work_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("document_ingest_batches.id", ondelete="CASCADE"), nullable=False,
    )
    client_key: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upload_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ingest_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    searchable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stored_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("stored_objects.id", ondelete="SET NULL"), nullable=True,
    )
    document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    graph_work_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
