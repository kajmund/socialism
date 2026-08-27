"""Kund / Projekt scoping tables + customer_id on personas and configurations.

Revision ID: 033_kunder_projekt_scoping
Revises: 032_panel_session_result
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "033_kunder_projekt_scoping"
down_revision: Union[str, Sequence[str], None] = "032_panel_session_result"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kunder",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_kunder_slug"),
    )
    op.create_index(op.f("ix_kunder_slug"), "kunder", ["slug"], unique=False)

    op.create_table(
        "projekt",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "slug", name="uq_projekt_customer_slug"),
    )
    op.create_index(op.f("ix_projekt_customer_id"), "projekt", ["customer_id"], unique=False)

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO kunder (id, name, slug, created_at, updated_at) VALUES "
            "(1, 'Devbrains', 'devbrains', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "(2, 'Bolag demo', 'bolag-demo', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO projekt (customer_id, name, slug, created_at, updated_at) VALUES "
            "(1, 'Default', 'default', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )

    op.add_column("personas", sa.Column("customer_id", sa.Integer(), nullable=True))
    conn.execute(sa.text("UPDATE personas SET customer_id = 1"))
    with op.batch_alter_table("personas") as batch_op:
        batch_op.alter_column("customer_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_personas_customer_id_kunder",
            "kunder",
            ["customer_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_personas_customer_id", ["customer_id"], unique=False)

    op.add_column("configurations", sa.Column("customer_id", sa.Integer(), nullable=True))
    conn.execute(sa.text("UPDATE configurations SET customer_id = 1"))
    with op.batch_alter_table("configurations") as batch_op:
        batch_op.alter_column("customer_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_configurations_customer_id_kunder",
            "kunder",
            ["customer_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_configurations_customer_id",
            ["customer_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("configurations") as batch_op:
        batch_op.drop_index("ix_configurations_customer_id")
        batch_op.drop_constraint("fk_configurations_customer_id_kunder", type_="foreignkey")
        batch_op.drop_column("customer_id")

    with op.batch_alter_table("personas") as batch_op:
        batch_op.drop_index("ix_personas_customer_id")
        batch_op.drop_constraint("fk_personas_customer_id_kunder", type_="foreignkey")
        batch_op.drop_column("customer_id")

    op.drop_index(op.f("ix_projekt_customer_id"), table_name="projekt")
    op.drop_table("projekt")
    op.drop_index(op.f("ix_kunder_slug"), table_name="kunder")
    op.drop_table("kunder")
