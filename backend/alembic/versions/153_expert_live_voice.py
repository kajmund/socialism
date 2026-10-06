"""Store the live-voice provider and voice on each expert."""

import sqlalchemy as sa
from alembic import op

revision = "153_expert_live_voice"
down_revision = "152_workspace_chat_documents"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("personas") as batch:
        batch.add_column(sa.Column("live_voice_provider", sa.String(16), nullable=True))
        batch.add_column(sa.Column("live_voice", sa.String(128), nullable=True))


def downgrade():
    with op.batch_alter_table("personas") as batch:
        batch.drop_column("live_voice")
        batch.drop_column("live_voice_provider")
