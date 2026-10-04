"""Object metadata with an explicit workspace for private document underlag."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class StoredObject(Base):
    __tablename__ = "stored_objects"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key", name="uq_stored_objects_bucket_key"),
        ForeignKeyConstraint(
            ["customer_id", "workspace_id"],
            ["workspaces.customer_id", "workspaces.id"],
            name="fk_stored_objects_workspace_customer",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    module: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("dd_campaigns.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    report_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    knowledge_status: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    knowledge_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    folder_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("underlag_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
