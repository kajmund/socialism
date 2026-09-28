"""Internal answer review schedules and candidate lifecycle."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base


class KnowledgeAnswerReview(Base):
    """Review reminder/candidate for one immutable tenant question + claim set."""

    __tablename__ = "knowledge_answer_reviews"
    __table_args__ = (
        CheckConstraint("ttl IN ('soon', 'later', 'never')", name="ck_answer_review_ttl"),
        CheckConstraint(
            "status IN ('scheduled', 'candidate', 'completed')",
            name="ck_answer_review_status",
        ),
        CheckConstraint(
            "(ttl = 'never' AND review_after IS NULL) OR "
            "(ttl IN ('soon', 'later') AND review_after IS NOT NULL)",
            name="ck_answer_review_date",
        ),
        Index("ix_answer_review_due", "status", "review_after", "id"),
        Index("ix_answer_review_customer", "customer_id", "status", "review_after", "id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("kunder.id", ondelete="RESTRICT"), nullable=False,
    )
    question_key: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    claim_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    ttl: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    candidate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
