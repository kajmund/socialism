"""Source-quality and research-gap observations. Not knowledge claims."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base


class KnowledgeObservationRecord(Base):
    """Source-quality or research-gap note. Not a durable knowledge claim."""

    __tablename__ = "knowledge_observations"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "observation_class",
            "kind",
            "document_version_id",
            "question_key",
            "statement_normalized",
            name="uq_knowledge_observations_identity",
        ),
        Index("ix_knowledge_observations_document_version", "document_version_id"),
        Index("ix_knowledge_observations_class", "observation_class"),
        CheckConstraint(
            "(scope_type = 'shared' AND customer_id IS NULL AND scope_key = 'shared') OR "
            "(scope_type = 'customer' AND customer_id IS NOT NULL AND "
            "scope_key = 'customer:' || customer_id)",
            name="ck_knowledge_observations_knowledge_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    observation_class: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    statement_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
