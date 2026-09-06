"""Add personal underlag folders.

Revision ID: 051_underlag_folders
Revises: 050_expert_population_customer_scope
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "051_underlag_folders"
down_revision: Union[str, Sequence[str], None] = "050_expert_population_customer_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "underlag_folders",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("parent_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["underlag_folders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_underlag_folders_customer_id", "underlag_folders", ["customer_id"])
    op.create_index("ix_underlag_folders_owner_user_id", "underlag_folders", ["owner_user_id"])
    op.create_index("ix_underlag_folders_module", "underlag_folders", ["module"])
    op.create_index("ix_underlag_folders_parent_id", "underlag_folders", ["parent_id"])

    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.add_column(sa.Column("folder_id", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_stored_objects_folder_id", ["folder_id"])
        batch_op.create_foreign_key(
            "fk_stored_objects_folder_id",
            "underlag_folders",
            ["folder_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.drop_constraint("fk_stored_objects_folder_id", type_="foreignkey")
        batch_op.drop_index("ix_stored_objects_folder_id")
        batch_op.drop_column("folder_id")
    op.drop_index("ix_underlag_folders_parent_id", table_name="underlag_folders")
    op.drop_index("ix_underlag_folders_module", table_name="underlag_folders")
    op.drop_index("ix_underlag_folders_owner_user_id", table_name="underlag_folders")
    op.drop_index("ix_underlag_folders_customer_id", table_name="underlag_folders")
    op.drop_table("underlag_folders")
