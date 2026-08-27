"""Project scoping on runs/messages/local catalog + customer_id on DD campaigns.

Revision ID: 034_project_scoping_and_dd_customer
Revises: 033_kunder_projekt_scoping
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034_project_scoping_and_dd_customer"
down_revision: Union[str, Sequence[str], None] = "033_kunder_projekt_scoping"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default projekt seeded in 033 under Devbrains (customer_id=1).
_DEFAULT_PROJECT_ID = 1
# Bolag demo kund seeded in 033 for DD module.
_BOLAG_DEMO_CUSTOMER_ID = 2


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column("runs", sa.Column("project_id", sa.Integer(), nullable=True))
    conn.execute(sa.text(f"UPDATE runs SET project_id = {_DEFAULT_PROJECT_ID}"))
    with op.batch_alter_table("runs") as batch_op:
        batch_op.alter_column("project_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_runs_project_id_projekt",
            "projekt",
            ["project_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_runs_project_id", ["project_id"], unique=False)

    op.add_column("messages", sa.Column("project_id", sa.Integer(), nullable=True))
    conn.execute(sa.text(f"UPDATE messages SET project_id = {_DEFAULT_PROJECT_ID}"))
    with op.batch_alter_table("messages") as batch_op:
        batch_op.alter_column("project_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_messages_project_id_projekt",
            "projekt",
            ["project_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_messages_project_id", ["project_id"], unique=False)

    op.add_column("catalog_lists", sa.Column("project_id", sa.Integer(), nullable=True))
    conn.execute(
        sa.text(
            f"UPDATE catalog_lists SET project_id = {_DEFAULT_PROJECT_ID} "
            "WHERE key = 'ort'"
        )
    )
    with op.batch_alter_table("catalog_lists") as batch_op:
        batch_op.drop_constraint("uq_catalog_lists_config_key", type_="unique")
        batch_op.create_foreign_key(
            "fk_catalog_lists_project_id_projekt",
            "projekt",
            ["project_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_catalog_lists_project_id", ["project_id"], unique=False)

    op.create_index(
        "uq_catalog_lists_config_key_global",
        "catalog_lists",
        ["configuration_id", "key"],
        unique=True,
        sqlite_where=sa.text("project_id IS NULL"),
    )
    op.create_index(
        "uq_catalog_lists_config_project_key",
        "catalog_lists",
        ["configuration_id", "project_id", "key"],
        unique=True,
        sqlite_where=sa.text("project_id IS NOT NULL"),
    )

    op.add_column("dd_campaigns", sa.Column("customer_id", sa.Integer(), nullable=True))
    conn.execute(
        sa.text(f"UPDATE dd_campaigns SET customer_id = {_BOLAG_DEMO_CUSTOMER_ID}")
    )
    with op.batch_alter_table("dd_campaigns") as batch_op:
        batch_op.alter_column("customer_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_dd_campaigns_customer_id_kunder",
            "kunder",
            ["customer_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_dd_campaigns_customer_id", ["customer_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("dd_campaigns") as batch_op:
        batch_op.drop_index("ix_dd_campaigns_customer_id")
        batch_op.drop_constraint("fk_dd_campaigns_customer_id_kunder", type_="foreignkey")
        batch_op.drop_column("customer_id")

    op.drop_index("uq_catalog_lists_config_project_key", table_name="catalog_lists")
    op.drop_index("uq_catalog_lists_config_key_global", table_name="catalog_lists")

    with op.batch_alter_table("catalog_lists") as batch_op:
        batch_op.drop_index("ix_catalog_lists_project_id")
        batch_op.drop_constraint("fk_catalog_lists_project_id_projekt", type_="foreignkey")
        batch_op.drop_column("project_id")
        batch_op.create_unique_constraint(
            "uq_catalog_lists_config_key",
            ["configuration_id", "key"],
        )

    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_index("ix_messages_project_id")
        batch_op.drop_constraint("fk_messages_project_id_projekt", type_="foreignkey")
        batch_op.drop_column("project_id")

    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_index("ix_runs_project_id")
        batch_op.drop_constraint("fk_runs_project_id_projekt", type_="foreignkey")
        batch_op.drop_column("project_id")
