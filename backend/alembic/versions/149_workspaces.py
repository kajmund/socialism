"""Separate company knowledge, client workspaces and workspace-bound chats."""

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "149_workspaces"
down_revision = "148_expert_async_tool_prompts"
branch_labels = None
depends_on = None


def _create_workspaces() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("kunder.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(64),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('company', 'client')", name="ck_workspaces_kind"),
        sa.UniqueConstraint("customer_id", "id", name="uq_workspaces_customer_id"),
    )
    op.create_index("ix_workspaces_customer_id", "workspaces", ["customer_id"])
    op.create_index(
        "uq_workspaces_company",
        "workspaces",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'company'"),
        sqlite_where=sa.text("kind = 'company'"),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column(
            "workspace_id",
            sa.String(64),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('manager', 'member')", name="ck_workspace_memberships_role"),
    )


def _create_chats() -> None:
    op.create_table(
        "workspace_chats",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.String(64),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("persona_id", sa.String(64), sa.ForeignKey("personas.id", ondelete="SET NULL")),
        sa.Column("module", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "workspace_id"],
            ["workspaces.customer_id", "workspaces.id"],
            name="fk_workspace_chats_workspace_customer",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_workspace_chats_customer_id", "workspace_chats", ["customer_id"])
    op.create_index("ix_workspace_chats_workspace_id", "workspace_chats", ["workspace_id"])
    op.create_index(
        "ix_workspace_chats_owner_workspace", "workspace_chats", ["owner_user_id", "workspace_id"]
    )
    op.create_table(
        "workspace_chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "chat_id",
            sa.String(64),
            sa.ForeignKey("workspace_chats.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "attachment_object_id",
            sa.String(64),
            sa.ForeignKey("stored_objects.id", ondelete="SET NULL"),
        ),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'tool')",
            name="ck_workspace_chat_messages_role",
        ),
    )
    op.create_index(
        "ix_workspace_chat_messages_chat_created",
        "workspace_chat_messages",
        ["chat_id", "created_at"],
    )


def _assign_existing_underlag(connection) -> None:
    customers = connection.execute(
        sa.text("SELECT id, name, organization_name FROM kunder")
    ).mappings()
    for customer in customers:
        workspace_id = str(uuid5(NAMESPACE_URL, f"socialism:company-workspace:{customer['id']}"))
        connection.execute(
            sa.text(
                "INSERT INTO workspaces (id, customer_id, name, kind) VALUES (:id, :customer_id, :name, 'company')"
            ),
            {
                "id": workspace_id,
                "customer_id": customer["id"],
                "name": customer["organization_name"] or customer["name"],
            },
        )
        connection.execute(
            sa.text(
                "UPDATE stored_objects SET workspace_id = :workspace_id WHERE customer_id = :customer_id AND kind = 'underlag'"
            ),
            {"workspace_id": workspace_id, "customer_id": customer["id"]},
        )
        connection.execute(
            sa.text(
                "UPDATE knowledge_questions SET namespace = :namespace WHERE customer_id = :customer_id AND namespace = :previous"
            ),
            {
                "namespace": f"tenant:{customer['id']}:workspace:{workspace_id}",
                "customer_id": customer["id"],
                "previous": f"tenant:{customer['id']}",
            },
        )


def _secure_backend_tables(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    for table in (
        "workspaces",
        "workspace_memberships",
        "workspace_chats",
        "workspace_chat_messages",
        "stored_objects",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""DO $$ DECLARE client_role text; BEGIN
        FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
        EXECUTE format('REVOKE ALL ON TABLE {table} FROM %I', client_role);
        END LOOP; END $$""")


def upgrade() -> None:
    connection = op.get_bind()
    _create_workspaces()
    with op.batch_alter_table("stored_objects") as batch:
        batch.add_column(sa.Column("workspace_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_stored_objects_workspace_customer",
            "workspaces",
            ["customer_id", "workspace_id"],
            ["customer_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_stored_objects_workspace_id", ["workspace_id"])
    _assign_existing_underlag(connection)
    _create_chats()
    _secure_backend_tables(connection)


def downgrade() -> None:
    connection = op.get_bind()
    for customer_id, workspace_id in connection.execute(
        sa.text("SELECT customer_id, id FROM workspaces WHERE kind = 'company'")
    ):
        connection.execute(
            sa.text(
                "UPDATE knowledge_questions SET namespace = :previous WHERE namespace = :namespace"
            ),
            {
                "previous": f"tenant:{customer_id}",
                "namespace": f"tenant:{customer_id}:workspace:{workspace_id}",
            },
        )
    op.drop_table("workspace_chat_messages")
    op.drop_table("workspace_chats")
    with op.batch_alter_table("stored_objects") as batch:
        batch.drop_index("ix_stored_objects_workspace_id")
        batch.drop_constraint("fk_stored_objects_workspace_customer", type_="foreignkey")
        batch.drop_column("workspace_id")
    op.drop_table("workspace_memberships")
    op.drop_table("workspaces")
