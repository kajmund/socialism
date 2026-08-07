"""Scope catalog_lists to configurations (grunddata per config).

Revision ID: 013_catalog_per_configuration
Revises: 012_configuration_prompts_map
Create Date: 2026-08-06
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.catalog_defaults import CATALOG_DEFAULTS

revision: str = "013_catalog_per_configuration"
down_revision: Union[str, Sequence[str], None] = "012_configuration_prompts_map"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _default_items_json(items: list) -> str:
    """Serialize default items for SQL insert (JSON column)."""
    out: list[dict] = []
    for item in items:
        row: dict = {
            "label": item["label"],
            "description": item.get("description") or "",
            "bounds": item.get("bounds"),
        }
        out.append(row)
    return json.dumps(out)


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "catalog_lists_new",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("configuration_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["configuration_id"],
            ["configurations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("configuration_id", "key", name="uq_catalog_lists_config_key"),
    )
    op.create_index(
        "ix_catalog_lists_new_configuration_id",
        "catalog_lists_new",
        ["configuration_id"],
        unique=False,
    )
    op.create_index(
        "ix_catalog_lists_new_section",
        "catalog_lists_new",
        ["section"],
        unique=False,
    )

    configs = conn.execute(
        sa.text(
            "SELECT id, is_active FROM configurations ORDER BY is_active DESC, id ASC"
        )
    ).fetchall()
    config_ids = [int(row[0]) for row in configs]
    active_id = next((int(row[0]) for row in configs if row[1]), None)
    if active_id is None and config_ids:
        active_id = config_ids[0]

    old_rows = conn.execute(
        sa.text("SELECT key, section, title, items, updated_at FROM catalog_lists")
    ).fetchall()

    if active_id is not None and old_rows:
        for key, section, title, items, updated_at in old_rows:
            conn.execute(
                sa.text(
                    "INSERT INTO catalog_lists_new "
                    "(configuration_id, key, section, title, items, updated_at) "
                    "VALUES (:configuration_id, :key, :section, :title, :items, :updated_at)"
                ),
                {
                    "configuration_id": active_id,
                    "key": key,
                    "section": section,
                    "title": title,
                    "items": items if isinstance(items, str) else json.dumps(items),
                    "updated_at": updated_at,
                },
            )

    # Seed defaults for every other configuration (and for active if it had no rows).
    for configuration_id in config_ids:
        existing_keys = {
            row[0]
            for row in conn.execute(
                sa.text(
                    "SELECT key FROM catalog_lists_new WHERE configuration_id = :cid"
                ),
                {"cid": configuration_id},
            ).fetchall()
        }
        for default in CATALOG_DEFAULTS:
            if default["key"] in existing_keys:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO catalog_lists_new "
                    "(configuration_id, key, section, title, items, updated_at) "
                    "VALUES (:configuration_id, :key, :section, :title, :items, CURRENT_TIMESTAMP)"
                ),
                {
                    "configuration_id": configuration_id,
                    "key": default["key"],
                    "section": default["section"],
                    "title": default["title"],
                    "items": _default_items_json(list(default["items"])),
                },
            )

    op.drop_table("catalog_lists")
    op.rename_table("catalog_lists_new", "catalog_lists")
    # Recreate index names to match SQLAlchemy conventions after rename.
    op.drop_index("ix_catalog_lists_new_configuration_id", table_name="catalog_lists")
    op.drop_index("ix_catalog_lists_new_section", table_name="catalog_lists")
    op.create_index(
        "ix_catalog_lists_configuration_id",
        "catalog_lists",
        ["configuration_id"],
        unique=False,
    )
    op.create_index(
        "ix_catalog_lists_section",
        "catalog_lists",
        ["section"],
        unique=False,
    )


def downgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "catalog_lists_old",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_catalog_lists_old_section",
        "catalog_lists_old",
        ["section"],
        unique=False,
    )

    active = conn.execute(
        sa.text(
            "SELECT id FROM configurations WHERE is_active = 1 ORDER BY id ASC LIMIT 1"
        )
    ).fetchone()
    if active is None:
        active = conn.execute(
            sa.text("SELECT id FROM configurations ORDER BY id ASC LIMIT 1")
        ).fetchone()

    if active is not None:
        rows = conn.execute(
            sa.text(
                "SELECT key, section, title, items, updated_at "
                "FROM catalog_lists WHERE configuration_id = :cid"
            ),
            {"cid": int(active[0])},
        ).fetchall()
        for key, section, title, items, updated_at in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO catalog_lists_old (key, section, title, items, updated_at) "
                    "VALUES (:key, :section, :title, :items, :updated_at)"
                ),
                {
                    "key": key,
                    "section": section,
                    "title": title,
                    "items": items if isinstance(items, str) else json.dumps(items),
                    "updated_at": updated_at,
                },
            )

    op.drop_table("catalog_lists")
    op.rename_table("catalog_lists_old", "catalog_lists")
    op.drop_index("ix_catalog_lists_old_section", table_name="catalog_lists")
    op.create_index("ix_catalog_lists_section", "catalog_lists", ["section"], unique=False)
