"""Database prompt fields for scoped chat and frozen research answers."""

import sqlalchemy as sa
from alembic import op

from app.services.prompt_defaults import modules_for_prompt_key
from app.services.workspace_chat_prompts import workspace_prompt_fields

revision = "150_workspace_chat_prompts"
down_revision = "149_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for field in workspace_prompt_fields():
        if (
            connection.execute(
                sa.text("SELECT id FROM prompt_fields WHERE key=:key"), {"key": field["key"]}
            ).first()
            is not None
        ):
            continue
        connection.execute(
            sa.text(
                "INSERT INTO prompt_fields (key,modules,section,label_sv,label_en,hint_sv,hint_en,"
                "default_sv,default_en,default_nb,active) VALUES (:key,:modules,:section,:label_sv,"
                ":label_en,:hint_sv,:hint_en,:default_sv,:default_en,:default_nb,TRUE)"
            ).bindparams(sa.bindparam("modules", type_=sa.JSON())),
            {
                "key": field["key"],
                "modules": modules_for_prompt_key(field["key"]),
                "section": "chat",
                "label_sv": field["label"]["sv"],
                "label_en": field["label"]["en"],
                "hint_sv": field["hint"]["sv"],
                "hint_en": field["hint"]["en"],
                "default_sv": field["defaults"]["sv"],
                "default_en": field["defaults"]["en"],
                "default_nb": field["defaults"]["nb"],
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    keys = [field["key"] for field in workspace_prompt_fields()]
    for key in keys:
        connection.execute(
            sa.text(
                "DELETE FROM prompt_overrides WHERE prompt_field_id IN "
                "(SELECT id FROM prompt_fields WHERE key=:key)"
            ),
            {"key": key},
        )
        connection.execute(sa.text("DELETE FROM prompt_fields WHERE key=:key"), {"key": key})
