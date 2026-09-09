"""Add Word batch moderator prompt and update raise-hand/comment.

Revision ID: 056_word_moderator_batch
Revises: 055_rattsunderlag_sessions
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "056_word_moderator_batch"
down_revision: Union[str, Sequence[str], None] = "055_rattsunderlag_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_RAISE_HAND_SV = (
    "Din roll: {label}\n"
    "Profil: {profile}\n\n"
    "Hela dokumentet ligger i systemmeddelandet (index i hakparentes, "
    "klausulnummer om det finns).\n\n"
    "Den här batchen (bara dessa index får du räcka upp handen för):\n"
    "{batch_text}\n\n"
    "Räck upp handen bara för de stycken där din kärnkompetens ger dig något konkret "
    "att säga. En tom lista är det normala och förväntade svaret. Vid tvekan: hoppa över.\n"
    "Returnera paragraph_indexes: en lista med styckesindex från batchen. Inga andra index."
)
_OLD_RAISE_HAND_EN = (
    "Your role: {label}\n"
    "Profile: {profile}\n\n"
    "The full document is in the system message (index in brackets, "
    "clause number if present).\n\n"
    "This batch (you may raise a hand only for these indexes):\n"
    "{batch_text}\n\n"
    "Raise your hand only for paragraphs where your core competence gives you "
    "something concrete to say. An empty list is the normal, expected answer. "
    "When in doubt: skip.\n"
    "Return paragraph_indexes: a list of paragraph indexes from the batch. No others."
)
_OLD_COMMENT_SV = (
    "Din roll: {label}\n"
    "Profil: {profile}\n\n"
    "Hela dokumentet ligger i systemmeddelandet.\n\n"
    "Avsnitt: {section_heading}\n"
    "Klausulnummer (internt): {list_string}\n\n"
    "Stycke du räckt upp handen för:\n{paragraph_text}\n\n"
    "Skriv en konkret kommentar till juristen. Tom kommentar betyder att du hoppar över. "
    "Inga tekniska termer. Prefixera inte med klausulnummer."
)
_OLD_COMMENT_EN = (
    "Your role: {label}\n"
    "Profile: {profile}\n\n"
    "The full document is in the system message.\n\n"
    "Section: {section_heading}\n"
    "Clause number (internal): {list_string}\n\n"
    "Paragraph you raised a hand for:\n{paragraph_text}\n\n"
    "Write a concrete comment for the lawyer. An empty comment means skip. "
    "No technical terms. Do not prefix with the clause number."
)

_UPDATE_KEYS = (
    "expertgranskning.word.expert.raise_hand",
    "expertgranskning.word.expert.comment",
)
_NEW_KEY = "expertgranskning.word.moderator.batch"


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
    _update_defaults(
        conn,
        "expertgranskning.word.expert.raise_hand",
        sv=_OLD_RAISE_HAND_SV,
        en=_OLD_RAISE_HAND_EN,
        nb=_OLD_RAISE_HAND_SV,
    )
    _update_defaults(
        conn,
        "expertgranskning.word.expert.comment",
        sv=_OLD_COMMENT_SV,
        en=_OLD_COMMENT_EN,
        nb=_OLD_COMMENT_SV,
    )
