"""Unique (module, sort_order) on panel catalog tables.

Revision ID: 043_panel_catalog_unique_sort_order
Revises: 042_kund_available_modules
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "043_panel_catalog_unique_sort_order"
down_revision: Union[str, Sequence[str], None] = "042_kund_available_modules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _densify_sort_order(table: str) -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            f"SELECT id, module, sort_order FROM {table} "
            "ORDER BY module ASC, sort_order ASC, id ASC"
        )
    ).fetchall()
    last_module: str | None = None
    index = 0
    for row in rows:
        row_id, module, current = int(row[0]), str(row[1]), int(row[2])
        if module != last_module:
            last_module = module
            index = 0
        if current != index:
            conn.execute(
                sa.text(f"UPDATE {table} SET sort_order = :so WHERE id = :id"),
                {"so": index, "id": row_id},
            )
        index += 1


def upgrade() -> None:
    _densify_sort_order("panel_sub_questions")
    _densify_sort_order("panel_expert_profiles")
    with op.batch_alter_table("panel_sub_questions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_panel_sub_questions_module_sort_order",
            ["module", "sort_order"],
        )
    with op.batch_alter_table("panel_expert_profiles") as batch_op:
        batch_op.create_unique_constraint(
            "uq_panel_expert_profiles_module_sort_order",
            ["module", "sort_order"],
        )


def downgrade() -> None:
    with op.batch_alter_table("panel_expert_profiles") as batch_op:
        batch_op.drop_constraint(
            "uq_panel_expert_profiles_module_sort_order", type_="unique"
        )
    with op.batch_alter_table("panel_sub_questions") as batch_op:
        batch_op.drop_constraint(
            "uq_panel_sub_questions_module_sort_order", type_="unique"
        )
