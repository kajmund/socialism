"""Indexed TTL review candidates, separate from evidence validity.

Revision ID: 124_knowledge_answer_review_ttl
Revises: 668bd23eb2df
"""

import sqlalchemy as sa
from alembic import op

revision = "124_knowledge_answer_review_ttl"
down_revision = "668bd23eb2df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_answer_reviews",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("question_key", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("claim_ids", sa.JSON(), nullable=False),
        sa.Column("ttl", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_after", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("candidate_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("ttl IN ('soon', 'later', 'never')", name="ck_answer_review_ttl"),
        sa.CheckConstraint(
            "status IN ('scheduled', 'candidate', 'completed')",
            name="ck_answer_review_status",
        ),
        sa.CheckConstraint(
            "(ttl = 'never' AND review_after IS NULL) OR "
            "(ttl IN ('soon', 'later') AND review_after IS NOT NULL)",
            name="ck_answer_review_date",
        ),
    )
    op.create_index(
        "ix_answer_review_due",
        "knowledge_answer_reviews",
        ["status", "review_after", "id"],
    )
    op.create_index(
        "ix_answer_review_customer",
        "knowledge_answer_reviews",
        ["customer_id", "status", "review_after", "id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        # Internal backend/worker table; no direct browser Data API access.
        op.execute("ALTER TABLE knowledge_answer_reviews ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("knowledge_answer_reviews")
