"""Scope panel expert profiles and populations to a customer.

Revision ID: 050_expert_population_customer_scope
Revises: 049_stored_object_underlag
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "050_expert_population_customer_scope"
down_revision: Union[str, Sequence[str], None] = "049_stored_object_underlag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OS_SLUG = "devbrains"


def _os_customer_id(conn) -> int:
    row = conn.execute(
        sa.text("SELECT id FROM kunder WHERE slug = :slug"),
        {"slug": _OS_SLUG},
    ).fetchone()
    if row is not None:
        return int(row[0])
    fallback = conn.execute(sa.text("SELECT id FROM kunder ORDER BY id ASC LIMIT 1")).fetchone()
    if fallback is None:
        raise RuntimeError("Cannot backfill customer_id: no kunder rows")
    return int(fallback[0])


def _rename_expert_persona_ids(conn) -> None:
    rows = conn.execute(
        sa.text("SELECT id, customer_id FROM personas WHERE kind = 'expert'")
    ).fetchall()
    for old_id, customer_id in rows:
        text_id = str(old_id)
        prefix = f"exp_{int(customer_id)}_"
        if text_id.startswith(prefix):
            continue
        key = text_id[4:] if text_id.startswith("exp_") else text_id
        new_id = f"{prefix}{key}"
        if new_id == text_id:
            continue
        conn.execute(
            sa.text("UPDATE population_members SET persona_id = :new WHERE persona_id = :old"),
            {"new": new_id, "old": text_id},
        )
        conn.execute(
            sa.text("UPDATE persona_messages SET persona_id = :new WHERE persona_id = :old"),
            {"new": new_id, "old": text_id},
        )
        conn.execute(
            sa.text("UPDATE personas SET id = :new WHERE id = :old"),
            {"new": new_id, "old": text_id},
        )


def upgrade() -> None:
    conn = op.get_bind()
    os_id = _os_customer_id(conn)

    op.add_column(
        "panel_expert_profiles",
        sa.Column("customer_id", sa.Integer(), nullable=True),
    )
    conn.execute(
        sa.text("UPDATE panel_expert_profiles SET customer_id = :cid"),
        {"cid": os_id},
    )
    with op.batch_alter_table("panel_expert_profiles") as batch_op:
        batch_op.alter_column("customer_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(
            batch_op.f("ix_panel_expert_profiles_customer_id"),
            ["customer_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_panel_expert_profiles_customer_id_kunder",
            "kunder",
            ["customer_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.drop_constraint("uq_panel_expert_profiles_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_panel_expert_profiles_customer_key",
            ["customer_id", "key"],
        )

    op.add_column(
        "populations",
        sa.Column("customer_id", sa.Integer(), nullable=True),
    )
    conn.execute(
        sa.text(
            """
            UPDATE populations
            SET customer_id = COALESCE((
                SELECT p.customer_id
                FROM population_members m
                JOIN personas p ON p.id = m.persona_id
                WHERE m.population_id = populations.id
                  AND m.persona_id IS NOT NULL
                ORDER BY m.id ASC
                LIMIT 1
            ), :os_id)
            """
        ),
        {"os_id": os_id},
    )
    inspector = sa.inspect(conn)
    name_uniques = [
        uq["name"]
        for uq in inspector.get_unique_constraints("populations")
        if list(uq.get("column_names") or []) == ["name"] and uq.get("name")
    ]
    name_indexes = [
        idx["name"]
        for idx in inspector.get_indexes("populations")
        if idx.get("unique") and list(idx.get("column_names") or []) == ["name"] and idx.get("name")
    ]
    with op.batch_alter_table("populations") as batch_op:
        batch_op.alter_column("customer_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(
            batch_op.f("ix_populations_customer_id"),
            ["customer_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_populations_customer_id_kunder",
            "kunder",
            ["customer_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        for name in name_uniques:
            batch_op.drop_constraint(name, type_="unique")
        for name in name_indexes:
            batch_op.drop_index(name)
        batch_op.create_unique_constraint(
            "uq_populations_customer_name",
            ["customer_id", "name"],
        )

    _rename_expert_persona_ids(conn)


def downgrade() -> None:
    with op.batch_alter_table("populations") as batch_op:
        batch_op.drop_constraint("uq_populations_customer_name", type_="unique")
        batch_op.create_unique_constraint("uq_populations_name", ["name"])
        batch_op.drop_constraint(
            "fk_populations_customer_id_kunder", type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_populations_customer_id"))
        batch_op.drop_column("customer_id")

    with op.batch_alter_table("panel_expert_profiles") as batch_op:
        batch_op.drop_constraint(
            "uq_panel_expert_profiles_customer_key", type_="unique"
        )
        batch_op.create_unique_constraint("uq_panel_expert_profiles_key", ["key"])
        batch_op.drop_constraint(
            "fk_panel_expert_profiles_customer_id_kunder", type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_panel_expert_profiles_customer_id"))
        batch_op.drop_column("customer_id")
