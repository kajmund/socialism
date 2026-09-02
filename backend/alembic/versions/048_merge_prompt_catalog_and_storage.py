"""Merge prompt catalog head with job-archive / stored-objects head.

Revision ID: 048_merge_prompt_catalog_and_storage
Revises: 046_prompt_fields_and_overrides, 047_stored_objects
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "048_merge_prompt_catalog_and_storage"
down_revision: Union[str, Sequence[str], None] = (
    "046_prompt_fields_and_overrides",
    "047_stored_objects",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
