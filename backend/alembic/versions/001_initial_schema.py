"""Initial schema: personas, populations, members, runs.

Revision ID: 001_initial
Revises:
Create Date: 2026-07-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personas",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("occ", sa.String(length=255), nullable=False),
        sa.Column("district", sa.String(length=255), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "populations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("versions", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.JSON(), nullable=False),
        sa.Column("recipe", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "population_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("population_id", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("initials", sa.String(length=8), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("occ", sa.String(length=255), nullable=False),
        sa.Column("district", sa.String(length=255), nullable=False),
        sa.Column("trait", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["population_id"], ["populations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_population_members_persona_id"),
        "population_members",
        ["persona_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_population_members_population_id"),
        "population_members",
        ["population_id"],
        unique=False,
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("population_id", sa.Integer(), nullable=False),
        sa.Column("seed", sa.String(length=64), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("main_ticks", sa.JSON(), nullable=False),
        sa.Column("branch", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["population_id"], ["populations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runs_population_id"), "runs", ["population_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_runs_population_id"), table_name="runs")
    op.drop_table("runs")
    op.drop_index(op.f("ix_population_members_population_id"), table_name="population_members")
    op.drop_index(op.f("ix_population_members_persona_id"), table_name="population_members")
    op.drop_table("population_members")
    op.drop_table("populations")
    op.drop_table("personas")
