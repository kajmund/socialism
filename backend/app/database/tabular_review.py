"""Persistent SSR Tabular Review objects and human verification labels."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base


class TabularReview(Base):
    """Named review: document set, columns, sort/filter, score threshold."""

    __tablename__ = "tabular_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    score_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.35)
    sort_key: Mapped[str] = mapped_column(String(64), nullable=False, default="document_title")
    sort_dir: Mapped[str] = mapped_column(String(8), nullable=False, default="asc")
    filter_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    columns: Mapped[list["TabularReviewColumn"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="TabularReviewColumn.sort_order",
    )
    rows: Mapped[list["TabularReviewRow"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
        order_by="TabularReviewRow.id",
    )
    cells: Mapped[list["TabularReviewCell"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
    )


class TabularReviewColumn(Base):
    """One SSR category/anchor column on a review."""

    __tablename__ = "tabular_review_columns"
    __table_args__ = (
        CheckConstraint(
            "polarity IN ('positive', 'negative')",
            name="ck_tabular_review_column_polarity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("tabular_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    anchor_set_id: Mapped[int] = mapped_column(
        ForeignKey("ssr_anchor_sets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    polarity: Mapped[str] = mapped_column(String(16), nullable=False, default="positive")
    allow_abstain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    abstain_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    review: Mapped[TabularReview] = relationship(back_populates="columns")


class TabularReviewRow(Base):
    """One agreement / CanonicalDocument on a review."""

    __tablename__ = "tabular_review_rows"
    __table_args__ = (
        UniqueConstraint("review_id", "document_id", name="uq_tabular_review_row_document"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("tabular_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    review: Mapped[TabularReview] = relationship(back_populates="rows")
    cells: Mapped[list["TabularReviewCell"]] = relationship(
        back_populates="row",
        cascade="all, delete-orphan",
    )


class TabularReviewCell(Base):
    """SSR match for one document × column, plus human review state."""

    __tablename__ = "tabular_review_cells"
    __table_args__ = (
        UniqueConstraint("review_id", "row_id", "column_id", name="uq_tabular_review_cell"),
        CheckConstraint(
            "status IN ('hit', 'no_hit', 'unknown', 'negative_hit')",
            name="ck_tabular_review_cell_status",
        ),
        CheckConstraint(
            "review_state IN ('pending', 'approved', 'rejected')",
            name="ck_tabular_review_cell_review_state",
        ),
        Index("ix_tabular_review_cells_review_row", "review_id", "row_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("tabular_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_id: Mapped[int] = mapped_column(
        ForeignKey("tabular_review_rows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    column_id: Mapped[int] = mapped_column(
        ForeignKey("tabular_review_columns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="no_hit")
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_unit_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exact_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    review: Mapped[TabularReview] = relationship(back_populates="cells")
    row: Mapped[TabularReviewRow] = relationship(back_populates="cells")
    candidates: Mapped[list["TabularReviewCandidate"]] = relationship(
        back_populates="cell",
        cascade="all, delete-orphan",
        order_by="TabularReviewCandidate.rank",
    )
    events: Mapped[list["TabularReviewCellEvent"]] = relationship(
        back_populates="cell",
        cascade="all, delete-orphan",
        order_by="TabularReviewCellEvent.id",
    )


class TabularReviewCandidate(Base):
    """Alternate TextUnit matches shown when a cell is expanded."""

    __tablename__ = "tabular_review_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cell_id: Mapped[int] = mapped_column(
        ForeignKey("tabular_review_cells.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    text_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exact_text: Mapped[str] = mapped_column(Text, nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    polarity: Mapped[str] = mapped_column(String(16), nullable=False, default="positive")
    source_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    cell: Mapped[TabularReviewCell] = relationship(back_populates="candidates")


class TabularReviewCellEvent(Base):
    """Audit history for cell actions."""

    __tablename__ = "tabular_review_cell_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cell_id: Mapped[int] = mapped_column(
        ForeignKey("tabular_review_cells.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    cell: Mapped[TabularReviewCell] = relationship(back_populates="events")


class TabularReviewVerificationLabel(Base):
    """Human label for exact category + TextUnit. Does not activate SSR anchors."""

    __tablename__ = "tabular_review_verification_labels"
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('match', 'not_match')",
            name="ck_tabular_review_label_verdict",
        ),
        Index(
            "ix_tabular_review_label_category_unit",
            "customer_id",
            "anchor_set_id",
            "label",
            "text_unit_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("tabular_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cell_id: Mapped[int] = mapped_column(
        ForeignKey("tabular_review_cells.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    anchor_set_id: Mapped[int] = mapped_column(
        ForeignKey("ssr_anchor_sets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    text_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    activated_as_ssr_anchor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class TabularReviewScoreCache(Base):
    """Cached cosine for (TextUnit, AnchorSet version, embedding model, label)."""

    __tablename__ = "tabular_review_score_cache"
    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_tabular_review_score_cache_key"),
    )

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    text_unit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    anchor_set_id: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_set_version: Mapped[str] = mapped_column(String(16), nullable=False)
    pool_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    polarity: Mapped[str] = mapped_column(String(16), nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
