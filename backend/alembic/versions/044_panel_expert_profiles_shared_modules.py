"""Share panel expert profiles across modules via modules JSON.

Revision ID: 044_panel_expert_profiles_shared_modules
Revises: 043_panel_catalog_unique_sort_order
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "044_panel_expert_profiles_shared_modules"
down_revision: Union[str, Sequence[str], None] = "043_panel_catalog_unique_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("panel_expert_profiles") as batch_op:
        batch_op.add_column(
            sa.Column(
                "modules",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, module FROM panel_expert_profiles")).fetchall()
    for row in rows:
        conn.execute(
            sa.text("UPDATE panel_expert_profiles SET modules = :modules WHERE id = :id"),
            {"modules": json.dumps([str(row[1])]), "id": int(row[0])},
        )

    with op.batch_alter_table("panel_expert_profiles") as batch_op:
        batch_op.drop_constraint("uq_panel_expert_profiles_module_key", type_="unique")
        batch_op.drop_constraint(
            "uq_panel_expert_profiles_module_sort_order", type_="unique"
        )
        batch_op.drop_index(op.f("ix_panel_expert_profiles_module"))
        batch_op.drop_column("module")
        batch_op.create_unique_constraint("uq_panel_expert_profiles_key", ["key"])


def downgrade() -> None:
    with op.batch_alter_table("panel_expert_profiles") as batch_op:
        batch_op.add_column(sa.Column("module", sa.String(length=32), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, modules FROM panel_expert_profiles")).fetchall()
    for row in rows:
        raw = row[1]
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw or []
        module = str(parsed[0]) if parsed else "dd"
        conn.execute(
            sa.text("UPDATE panel_expert_profiles SET module = :module WHERE id = :id"),
            {"module": module, "id": int(row[0])},
        )

    with op.batch_alter_table("panel_expert_profiles") as batch_op:
        batch_op.alter_column("module", existing_type=sa.String(length=32), nullable=False)
        batch_op.create_index(op.f("ix_panel_expert_profiles_module"), ["module"])
        batch_op.drop_constraint("uq_panel_expert_profiles_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_panel_expert_profiles_module_key", ["module", "key"]
        )
        batch_op.create_unique_constraint(
            "uq_panel_expert_profiles_module_sort_order", ["module", "sort_order"]
        )
        batch_op.drop_column("modules")
