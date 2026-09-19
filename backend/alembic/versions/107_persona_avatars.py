"""Persona profile photos in object storage."""

from alembic import op
import sqlalchemy as sa

revision = "107_persona_avatars"
down_revision = "106_mem0_postgres_storage"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("personas") as batch:
        batch.add_column(sa.Column("avatar_key", sa.String(255), nullable=True))
        batch.add_column(
            sa.Column("avatar_revision", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade():
    with op.batch_alter_table("personas") as batch:
        batch.drop_column("avatar_revision")
        batch.drop_column("avatar_key")
