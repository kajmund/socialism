"""Persistent SSR Tabular Review objects.

Revision ID: 193_tabular_reviews
Revises: 192_drop_graph_tables
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "193_tabular_reviews"
down_revision: str | Sequence[str] | None = "192_drop_graph_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tabular_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("kunder.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(64),
            sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("score_threshold", sa.Float(), nullable=False, server_default="0.35"),
        sa.Column("sort_key", sa.String(64), nullable=False, server_default="document_title"),
        sa.Column("sort_dir", sa.String(8), nullable=False, server_default="asc"),
        sa.Column("filter_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tabular_reviews_customer_id", "tabular_reviews", ["customer_id"])
    op.create_index("ix_tabular_reviews_created_by_user_id", "tabular_reviews", ["created_by_user_id"])

    op.create_table(
        "tabular_review_columns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("tabular_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "anchor_set_id",
            sa.Integer(),
            sa.ForeignKey("ssr_anchor_sets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("polarity", sa.String(16), nullable=False, server_default="positive"),
        sa.Column("allow_abstain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("abstain_margin", sa.Float(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("polarity IN ('positive', 'negative')", name="ck_tabular_review_column_polarity"),
    )
    op.create_index("ix_tabular_review_columns_review_id", "tabular_review_columns", ["review_id"])
    op.create_index("ix_tabular_review_columns_anchor_set_id", "tabular_review_columns", ["anchor_set_id"])

    op.create_table(
        "tabular_review_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("tabular_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("canonical_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            sa.String(64),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("source_object_id", sa.String(64), nullable=True),
        sa.UniqueConstraint("review_id", "document_id", name="uq_tabular_review_row_document"),
    )
    op.create_index("ix_tabular_review_rows_review_id", "tabular_review_rows", ["review_id"])
    op.create_index("ix_tabular_review_rows_document_id", "tabular_review_rows", ["document_id"])

    op.create_table(
        "tabular_review_cells",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("tabular_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "row_id",
            sa.Integer(),
            sa.ForeignKey("tabular_review_rows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "column_id",
            sa.Integer(),
            sa.ForeignKey("tabular_review_columns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="no_hit"),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("text_unit_id", sa.String(64), nullable=True),
        sa.Column("exact_text", sa.Text(), nullable=True),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("review_id", "row_id", "column_id", name="uq_tabular_review_cell"),
        sa.CheckConstraint(
            "status IN ('hit', 'no_hit', 'unknown', 'negative_hit')",
            name="ck_tabular_review_cell_status",
        ),
        sa.CheckConstraint(
            "review_state IN ('pending', 'approved', 'rejected')",
            name="ck_tabular_review_cell_review_state",
        ),
    )
    op.create_index("ix_tabular_review_cells_review_id", "tabular_review_cells", ["review_id"])
    op.create_index("ix_tabular_review_cells_row_id", "tabular_review_cells", ["row_id"])
    op.create_index("ix_tabular_review_cells_column_id", "tabular_review_cells", ["column_id"])
    op.create_index("ix_tabular_review_cells_review_row", "tabular_review_cells", ["review_id", "row_id"])

    op.create_table(
        "tabular_review_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "cell_id",
            sa.Integer(),
            sa.ForeignKey("tabular_review_cells.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("text_unit_id", sa.String(64), nullable=False),
        sa.Column("exact_text", sa.Text(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("polarity", sa.String(16), nullable=False, server_default="positive"),
        sa.Column("source_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_tabular_review_candidates_cell_id", "tabular_review_candidates", ["cell_id"])

    op.create_table(
        "tabular_review_cell_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "cell_id",
            sa.Integer(),
            sa.ForeignKey("tabular_review_cells.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tabular_review_cell_events_cell_id", "tabular_review_cell_events", ["cell_id"])

    op.create_table(
        "tabular_review_verification_labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("kunder.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by_user_id", sa.String(64), nullable=False),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("tabular_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cell_id",
            sa.Integer(),
            sa.ForeignKey("tabular_review_cells.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "anchor_set_id",
            sa.Integer(),
            sa.ForeignKey("ssr_anchor_sets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("text_unit_id", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("activated_as_ssr_anchor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("verdict IN ('match', 'not_match')", name="ck_tabular_review_label_verdict"),
    )
    op.create_index(
        "ix_tabular_review_verification_labels_customer_id",
        "tabular_review_verification_labels",
        ["customer_id"],
    )
    op.create_index(
        "ix_tabular_review_verification_labels_review_id",
        "tabular_review_verification_labels",
        ["review_id"],
    )
    op.create_index(
        "ix_tabular_review_verification_labels_cell_id",
        "tabular_review_verification_labels",
        ["cell_id"],
    )
    op.create_index(
        "ix_tabular_review_label_category_unit",
        "tabular_review_verification_labels",
        ["customer_id", "anchor_set_id", "label", "text_unit_id"],
    )

    op.create_table(
        "tabular_review_score_cache",
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column("text_unit_id", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("anchor_set_id", sa.Integer(), nullable=False),
        sa.Column("anchor_set_version", sa.String(16), nullable=False),
        sa.Column("pool_revision", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("polarity", sa.String(16), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("cache_key", name="uq_tabular_review_score_cache_key"),
    )
    op.create_index(
        "ix_tabular_review_score_cache_text_unit_id",
        "tabular_review_score_cache",
        ["text_unit_id"],
    )


def downgrade() -> None:
    op.drop_table("tabular_review_score_cache")
    op.drop_table("tabular_review_verification_labels")
    op.drop_table("tabular_review_cell_events")
    op.drop_table("tabular_review_candidates")
    op.drop_table("tabular_review_cells")
    op.drop_table("tabular_review_rows")
    op.drop_table("tabular_review_columns")
    op.drop_table("tabular_reviews")
