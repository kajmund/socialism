"""Internal answer review schedules and candidate lifecycle."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base


class KnowledgeAnswerReview(Base):
    """Review reminder for a question's complete, source-independent answer basis."""

    __tablename__ = "knowledge_answer_reviews"
    __table_args__ = (
        CheckConstraint("ttl IN ('soon', 'later', 'never')", name="ck_answer_review_ttl"),
        CheckConstraint(
            "status IN ('awaiting_ttl', 'scheduled', 'candidate', 'completed')",
            name="ck_answer_review_status",
        ),
        CheckConstraint(
            "(status = 'awaiting_ttl' AND ttl IS NULL AND review_after IS NULL) OR "
            "(status <> 'awaiting_ttl' AND ttl IS NOT NULL AND "
            "((ttl = 'never' AND review_after IS NULL) OR "
            "(ttl IN ('soon', 'later') AND review_after IS NOT NULL)))",
            name="ck_answer_review_date",
        ),
        Index("ix_answer_review_due", "status", "review_after", "id"),
        Index("ix_answer_review_customer", "customer_id", "status", "review_after", "id"),
        Index("ix_answer_review_classify", "status", "next_classification_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"),
        nullable=False,
    )
    question_key: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    answer_basis: Mapped[dict] = mapped_column(JSON, nullable=False)
    ttl: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    candidate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_classification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification_token: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(String(64))
    classification_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
