"""Add stored_objects for kund+module S3 files.

Revision ID: 047_stored_objects
Revises: 046_job_archived_at
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "047_stored_objects"
down_revision: Union[str, Sequence[str], None] = "046_job_archived_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stored_objects",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("bucket", sa.String(length=63), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("candidate_id", sa.String(length=64), nullable=True),
        sa.Column("report_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["dd_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket", "object_key", name="uq_stored_objects_bucket_key"),
    )
    op.create_index("ix_stored_objects_customer_id", "stored_objects", ["customer_id"])
    op.create_index("ix_stored_objects_module", "stored_objects", ["module"])
    op.create_index("ix_stored_objects_kind", "stored_objects", ["kind"])
    op.create_index("ix_stored_objects_campaign_id", "stored_objects", ["campaign_id"])
    op.create_index("ix_stored_objects_candidate_id", "stored_objects", ["candidate_id"])
    op.create_index("ix_stored_objects_report_id", "stored_objects", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_stored_objects_report_id", table_name="stored_objects")
    op.drop_index("ix_stored_objects_candidate_id", table_name="stored_objects")
    op.drop_index("ix_stored_objects_campaign_id", table_name="stored_objects")
    op.drop_index("ix_stored_objects_kind", table_name="stored_objects")
    op.drop_index("ix_stored_objects_module", table_name="stored_objects")
    op.drop_index("ix_stored_objects_customer_id", table_name="stored_objects")
    op.drop_table("stored_objects")
