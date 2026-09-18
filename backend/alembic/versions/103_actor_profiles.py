"""User profiles, organizations and consent-bound expert proposals."""

from alembic import op
import sqlalchemy as sa

revision = "103_actor_profiles"
down_revision = "102_document_knowledge"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_accounts") as b:
        b.add_column(sa.Column("first_name", sa.String(100), nullable=True))
        b.add_column(sa.Column("last_name", sa.String(100), nullable=True))
        b.add_column(sa.Column("job_title", sa.String(200), nullable=True))
        b.add_column(sa.Column("avatar_key", sa.String(255), nullable=True))
        b.add_column(
            sa.Column("profile_revision", sa.Integer(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("kunder") as b:
        b.add_column(sa.Column("organization_name", sa.String(255), nullable=True))
        b.add_column(sa.Column("organization_number", sa.String(40), nullable=True))
        b.add_column(sa.Column("address_line1", sa.String(255), nullable=True))
        b.add_column(sa.Column("address_line2", sa.String(255), nullable=True))
        b.add_column(sa.Column("postal_code", sa.String(32), nullable=True))
        b.add_column(sa.Column("city", sa.String(100), nullable=True))
        b.add_column(sa.Column("country_code", sa.String(2), nullable=True))
        b.add_column(
            sa.Column("profile_revision", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_table(
        "actor_context_proposals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("conversation", sa.String(255), nullable=False),
        sa.Column("target", sa.String(16), nullable=False),
        sa.Column("target_label", sa.String(255), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("previous", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table("actor_context_proposals")
    with op.batch_alter_table("user_accounts") as b:
        b.drop_column("first_name")
        b.drop_column("last_name")
        b.drop_column("job_title")
        b.drop_column("avatar_key")
        b.drop_column("profile_revision")
    with op.batch_alter_table("kunder") as b:
        b.drop_column("organization_name")
        b.drop_column("organization_number")
        b.drop_column("address_line1")
        b.drop_column("address_line2")
        b.drop_column("postal_code")
        b.drop_column("city")
        b.drop_column("country_code")
        b.drop_column("profile_revision")
