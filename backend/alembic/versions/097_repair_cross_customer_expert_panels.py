"""Repair expert panels linked to another customer's experts.

Revision ID: 097_repair_cross_customer_expert_panels
Revises: 096_sme_product_messenger
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "097_repair_cross_customer_expert_panels"
down_revision: str | Sequence[str] | None = "096_sme_product_messenger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERSONAS = sa.table(
    "personas",
    sa.column("id", sa.String),
    sa.column("customer_id", sa.Integer),
    sa.column("kind", sa.String),
    sa.column("name", sa.String),
    sa.column("age", sa.Integer),
    sa.column("occ", sa.String),
    sa.column("district", sa.String),
    sa.column("quote", sa.Text),
    sa.column("origin", sa.String),
    sa.column("profile", sa.JSON),
    sa.column("tools", sa.JSON),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _clone_id(customer_id: int, persona_id: str) -> str:
    digest = hashlib.sha1(f"{customer_id}:{persona_id}".encode()).hexdigest()[:20]
    return f"expert-{customer_id}-{digest}"


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT DISTINCT
                panel.customer_id AS target_customer_id,
                expert.id,
                expert.name,
                expert.age,
                expert.occ,
                expert.district,
                expert.quote,
                expert.origin,
                expert.profile,
                expert.tools,
                expert.updated_at
            FROM populations AS panel
            JOIN population_members AS member ON member.population_id = panel.id
            JOIN personas AS expert ON expert.id = member.persona_id
            WHERE panel.kind = 'expert_panel'
              AND expert.kind = 'expert'
              AND panel.customer_id <> expert.customer_id
            """
        )
    ).mappings()
    for row in rows:
        target_customer_id = int(row["target_customer_id"])
        old_id = str(row["id"])
        new_id = _clone_id(target_customer_id, old_id)
        exists = connection.execute(
            sa.text("SELECT 1 FROM personas WHERE id = :id"),
            {"id": new_id},
        ).first()
        if exists is None:
            profile = row["profile"]
            tools = row["tools"]
            updated_at = row["updated_at"]
            connection.execute(
                _PERSONAS.insert(),
                {
                    "id": new_id,
                    "customer_id": target_customer_id,
                    "kind": "expert",
                    "name": row["name"],
                    "age": row["age"],
                    "occ": row["occ"],
                    "district": row["district"],
                    "quote": row["quote"],
                    "origin": row["origin"],
                    "profile": json.loads(profile) if isinstance(profile, str) else profile,
                    "tools": json.loads(tools) if isinstance(tools, str) else tools,
                    "updated_at": (
                        datetime.fromisoformat(updated_at)
                        if isinstance(updated_at, str)
                        else updated_at
                    ),
                },
            )
        connection.execute(
            sa.text(
                """
                UPDATE population_members
                SET persona_id = :new_id
                WHERE persona_id = :old_id
                  AND population_id IN (
                      SELECT id
                      FROM populations
                      WHERE customer_id = :customer_id
                        AND kind = 'expert_panel'
                  )
                """
            ),
            {
                "new_id": new_id,
                "old_id": old_id,
                "customer_id": target_customer_id,
            },
        )


def downgrade() -> None:
    # Data repair is intentionally irreversible: cloned experts may gain chats
    # immediately after this migration.
    pass
