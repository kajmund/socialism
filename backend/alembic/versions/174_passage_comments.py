"""Comments can be attached to a marked passage."""

import sqlalchemy as sa
from alembic import op

revision = "174_passage_comments"
down_revision = "173_each_passage_is_marked"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_passage_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("passage_key", sa.Text(), nullable=False),
        sa.Column("anchor", sa.JSON(), nullable=False),
        sa.Column("author_user_id", sa.String(64), nullable=False),
        sa.Column("author_name", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["voice_workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workspace_passage_comments_workspace_id", "workspace_passage_comments", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_passage_comments_workspace_id", table_name="workspace_passage_comments")
    op.drop_table("workspace_passage_comments")
