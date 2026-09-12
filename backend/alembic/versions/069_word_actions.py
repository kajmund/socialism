"""Add persistent WordAction table and drop result application columns.

Revision ID: 069_word_actions
Revises: 068_word_application_lifecycle
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "069_word_actions"
down_revision: Union[str, Sequence[str], None] = "068_word_application_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "word_actions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_ordinal", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("anchor", sa.JSON(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("application_id", sa.String(length=64), nullable=True),
        sa.Column("application_error", sa.String(length=64), nullable=True),
        sa.Column("word_artifact_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            "source_ordinal",
            name="uq_word_actions_source",
        ),
    )
    op.create_index("ix_word_actions_job_id", "word_actions", ["job_id"])
    op.create_index("ix_word_actions_customer_id", "word_actions", ["customer_id"])
    op.create_index(
        "ix_word_actions_customer_job",
        "word_actions",
        ["customer_id", "job_id"],
    )
    op.create_index(
        "ix_word_actions_application_id",
        "word_actions",
        ["application_id"],
    )
    with op.batch_alter_table("expertgranskning_results") as batch_op:
        batch_op.drop_column("application_error")
        batch_op.drop_column("application_id")
        batch_op.drop_column("comment_id")
        batch_op.drop_column("status")


def downgrade() -> None:
    with op.batch_alter_table("expertgranskning_results") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("comment_id", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("application_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("application_error", sa.String(length=64), nullable=True)
        )
    op.execute(
        sa.text(
            "UPDATE expertgranskning_results "
            "SET status = 'pending' "
            "WHERE status IS NULL"
        )
    )
    with op.batch_alter_table("expertgranskning_results") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=32),
            nullable=False,
        )
    op.drop_index("ix_word_actions_application_id", table_name="word_actions")
    op.drop_index("ix_word_actions_customer_job", table_name="word_actions")
    op.drop_index("ix_word_actions_customer_id", table_name="word_actions")
    op.drop_index("ix_word_actions_job_id", table_name="word_actions")
    op.drop_table("word_actions")
