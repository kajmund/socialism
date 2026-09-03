"""Add personal underlag columns on stored_objects.

Revision ID: 049_stored_object_underlag
Revises: 048_merge_prompt_catalog_and_storage
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "049_stored_object_underlag"
down_revision: Union[str, Sequence[str], None] = "048_merge_prompt_catalog_and_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("extracted_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("extraction_status", sa.String(length=16), nullable=True))
        batch_op.create_index("ix_stored_objects_owner_user_id", ["owner_user_id"])
        batch_op.create_foreign_key(
            "fk_stored_objects_owner_user_id",
            "user_accounts",
            ["owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("stored_objects") as batch_op:
        batch_op.drop_constraint("fk_stored_objects_owner_user_id", type_="foreignkey")
        batch_op.drop_index("ix_stored_objects_owner_user_id")
        batch_op.drop_column("extraction_status")
        batch_op.drop_column("extracted_text")
        batch_op.drop_column("owner_user_id")
