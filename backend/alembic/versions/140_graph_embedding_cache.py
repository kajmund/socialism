"""Tenant-independent content-addressed graph embedding cache."""

import sqlalchemy as sa
from alembic import op

revision = "140_graph_embedding_cache"
down_revision = "139_graph_question_revalidation_work"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_embedding_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("model_revision", sa.String(128), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("normalized_text_hash", sa.String(64), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("lock_owner", sa.String(64), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "model", "model_revision", "dimension", "purpose", "normalized_text_hash",
            name="uq_graph_embedding_content",
        ),
    )
    op.create_index("ix_graph_embedding_lease", "graph_embedding_cache", ["status", "lock_expires_at"])
    op.create_index("ix_graph_embedding_last_used", "graph_embedding_cache", ["last_used_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE graph_embedding_cache ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("graph_embedding_cache")
