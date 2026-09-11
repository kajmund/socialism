"""Word comment anchors, party-neutral prompts, and JSON retry.

Revision ID: 064_word_comment_anchor_retry
Revises: 062_word_comment_convergence
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "064_word_comment_anchor_retry"
down_revision: Union[str, Sequence[str], None] = "062_word_comment_convergence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPDATE_KEYS = (
    "expertgranskning.word.expert.comment",
    "expertgranskning.word.comment_convergence",
)
_NEW_KEY = "expertgranskning.word.structured_retry"


def _field(key: str) -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == key)


def _update_defaults(conn, key: str, *, sv: str, en: str, nb: str) -> None:
    conn.execute(
        sa.text(
            "UPDATE prompt_fields "
            "SET default_sv = :sv, default_en = :en, default_nb = :nb "
            "WHERE key = :key"
        ).bindparams(sv=sv, en=en, nb=nb, key=key)
    )


def upgrade() -> None:
    conn = op.get_bind()
    for key in _UPDATE_KEYS:
        defaults = _field(key)["defaults"]
        _update_defaults(
            conn,
            key,
            sv=defaults["sv"],
            en=defaults["en"],
            nb=defaults["nb"],
        )

    exists = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
    ).fetchone()
    if exists is not None:
        return
    field = _field(_NEW_KEY)
    labels = field["label"]
    hints = field["hint"]
    defaults = field["defaults"]
    conn.execute(
        sa.text(
            "INSERT INTO prompt_fields ("
            "key, modules, section, label_sv, label_en, hint_sv, hint_en, "
            "default_sv, default_en, default_nb, active"
            ") VALUES ("
            ":key, :modules, :section, :label_sv, :label_en, :hint_sv, :hint_en, "
            ":default_sv, :default_en, :default_nb, 1"
            ")"
        ).bindparams(
            key=_NEW_KEY,
            modules=json.dumps(["expertgranskning"]),
            section=field["section"],
            label_sv=labels["sv"],
            label_en=labels["en"],
            hint_sv=hints["sv"],
            hint_en=hints["en"],
            default_sv=defaults["sv"],
            default_en=defaults["en"],
            default_nb=defaults["nb"],
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    field_id = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
    ).fetchone()
    if field_id is not None:
        conn.execute(
            sa.text(
                "DELETE FROM prompt_overrides WHERE prompt_field_id = :field_id"
            ).bindparams(field_id=field_id[0])
        )
        conn.execute(
            sa.text("DELETE FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
        )
