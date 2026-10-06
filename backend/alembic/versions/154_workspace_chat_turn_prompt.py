"""Prompt that gives expert text chat the current workspace selection."""

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision = "154_workspace_chat_turn_prompt"
down_revision = "153_expert_live_voice"
branch_labels = None
depends_on = None

KEY = "workspace.chat.turn"


def _field() -> dict:
    for field in PROMPT_FIELDS:
        if field["key"] == KEY:
            return field
    raise RuntimeError(f"missing prompt catalog field {KEY}")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT id FROM prompt_fields WHERE key=:key"), {"key": KEY}).first():
        return
    field = _field()
    connection.execute(
        sa.text(
            "INSERT INTO prompt_fields (key,modules,section,label_sv,label_en,hint_sv,hint_en,"
            "default_sv,default_en,default_nb,active) VALUES (:key,:modules,:section,:label_sv,"
            ":label_en,:hint_sv,:hint_en,:default_sv,:default_en,:default_nb,TRUE)"
        ).bindparams(sa.bindparam("modules", type_=sa.JSON())),
        {
            "key": KEY,
            "modules": modules_for_prompt_key(KEY),
            "section": field["section"],
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
    connection.execute(
        sa.text(
            "DELETE FROM prompt_overrides WHERE prompt_field_id IN "
            "(SELECT id FROM prompt_fields WHERE key=:key)"
        ),
        {"key": KEY},
    )
    connection.execute(sa.text("DELETE FROM prompt_fields WHERE key=:key"), {"key": KEY})
