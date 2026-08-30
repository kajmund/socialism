"""Add tools JSON column to personas.

Revision ID: 039_persona_tools
Revises: 038_dd_campaign_panel_assignments
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "039_persona_tools"
down_revision: Union[str, Sequence[str], None] = "038_dd_campaign_panel_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_EXPERT_TOOLS = (
    '["search_companies","lookup_company","validate_orgnr",'
    '"search_duckduckgo","search_wiki"]'
)


def upgrade() -> None:
    with op.batch_alter_table("personas") as batch_op:
        batch_op.add_column(sa.Column("tools", sa.JSON(), nullable=True))
    op.execute(
        sa.text(
            f"UPDATE personas SET tools = '{_DEFAULT_EXPERT_TOOLS}' WHERE kind = 'expert'"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("personas") as batch_op:
        batch_op.drop_column("tools")
