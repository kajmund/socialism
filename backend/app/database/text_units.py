"""Content-addressed text plus scoped document/version occurrences."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base
from app.database.chunk_guards import protect_shared_chunks, protect_text_unit_reference

if TYPE_CHECKING:
    from app.database.models import DocumentSectionRecord, DocumentVersionRecord


class SharedTextChunkRecord(Base):
    """Exact UTF-8 content stored once by SHA-256, independent of provenance."""

    __tablename__ = "shared_text_chunks"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)


protect_shared_chunks(SharedTextChunkRecord.__table__)


class TextUnitRecord(Base):
    """Scoped document occurrence referencing shared immutable chunk text."""

    __tablename__ = "text_units"
    __table_args__ = (
        Index("ix_text_units_document_ordinal", "document_id", "ordinal"),
        Index("ix_text_units_version_ordinal", "document_version_id", "ordinal"),
        Index("ix_text_units_content_hash", "content_hash"),
        CheckConstraint(
            "(scope_type = 'shared' AND customer_id IS NULL AND scope_key = 'shared') OR "
            "(scope_type = 'customer' AND customer_id IS NOT NULL AND "
            "scope_key = 'customer:' || customer_id)",
            name="ck_text_units_knowledge_scope",
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
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(
        ForeignKey("shared_text_chunks.content_hash", ondelete="RESTRICT"), nullable=False,
    )
    locator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    embedding_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    document_version: Mapped[DocumentVersionRecord] = relationship(back_populates="text_units")
    section: Mapped[DocumentSectionRecord | None] = relationship(back_populates="text_units")

    chunk: Mapped[SharedTextChunkRecord] = relationship(lazy="joined", innerjoin=True)

    @property
    def text(self) -> str:
        return self.chunk.text


protect_text_unit_reference(TextUnitRecord.__table__)
