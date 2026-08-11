"""Population member slot keys, generation staging table, fingerprint inferred flag.

Revision ID: 020_population_fingerprint_truth
Revises: 019_ssr_anchor_pool_items
Create Date: 2026-08-11
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_population_fingerprint_truth"
down_revision: Union[str, Sequence[str], None] = "019_ssr_anchor_pool_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "population_members",
        sa.Column("age_bucket", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "population_members",
        sa.Column("lean_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "population_members",
        sa.Column("district_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "populations",
        sa.Column(
            "fingerprint_inferred",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "population_generations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("recipe", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.JSON(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("qa_warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_population_generations_created_at",
        "population_generations",
        ["created_at"],
    )

    from app.services.population_fingerprint import (
        fingerprint_from_slot_rows,
        infer_age_bucket,
        infer_district_key,
        infer_lean_key_optional,
        lutning_from_profile,
    )

    bind = op.get_bind()
    population_rows = bind.execute(
        sa.text("SELECT id, recipe FROM populations")
    ).fetchall()
    member_rows = bind.execute(
        sa.text(
            "SELECT pm.id, pm.population_id, pm.age, pm.district, p.profile AS profile "
            "FROM population_members pm "
            "LEFT JOIN personas p ON p.id = pm.persona_id "
            "ORDER BY pm.id"
        )
    ).fetchall()

    recipes: dict[int, dict] = {}
    for row in population_rows:
        raw = row.recipe
        recipes[row.id] = json.loads(raw) if isinstance(raw, str) else (raw or {})

    members_by_pop: dict[int, list] = defaultdict(list)
    for row in member_rows:
        members_by_pop[row.population_id].append(row)

    for pop_id, recipe in recipes.items():
        members = members_by_pop.get(pop_id, [])
        if not members:
            continue
        dist = recipe.get("dist") or {}
        slot_rows = []
        for member in members:
            age_bucket = infer_age_bucket(int(member.age))
            district_key = infer_district_key(str(member.district), dist.get("district"))
            profile_raw = member.profile
            profile = (
                json.loads(profile_raw)
                if isinstance(profile_raw, str)
                else (profile_raw or {})
            )
            lean_key = infer_lean_key_optional(
                lutning_from_profile(profile),
                dist.get("leaning"),
            )
            slot_rows.append(
                {
                    "age_bucket": age_bucket,
                    "lean_key": lean_key,
                    "district_key": district_key,
                }
            )
            bind.execute(
                sa.text(
                    "UPDATE population_members "
                    "SET age_bucket = :age_bucket, lean_key = :lean_key, "
                    "district_key = :district_key WHERE id = :member_id"
                ),
                {
                    "age_bucket": age_bucket,
                    "lean_key": lean_key,
                    "district_key": district_key,
                    "member_id": member.id,
                },
            )
        new_fp = fingerprint_from_slot_rows(slot_rows, dist)
        bind.execute(
            sa.text(
                "UPDATE populations SET fingerprint = :fp, fingerprint_inferred = 1 "
                "WHERE id = :pop_id"
            ),
            {"fp": json.dumps(new_fp), "pop_id": pop_id},
        )


def downgrade() -> None:
    op.drop_index("ix_population_generations_created_at", table_name="population_generations")
    op.drop_table("population_generations")
    op.drop_column("populations", "fingerprint_inferred")
    op.drop_column("population_members", "district_key")
    op.drop_column("population_members", "lean_key")
    op.drop_column("population_members", "age_bucket")
