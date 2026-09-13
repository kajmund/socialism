"""Word review output contract and structured research decision.

Revision ID: 078_word_review_output_contract
Revises: 077_word_review_atomic_observations
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "078_word_review_output_contract"
down_revision: Union[str, Sequence[str], None] = "077_word_review_atomic_observations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UPDATE_KEYS = (
    "panel.moderator.system",
    "panel.moderator.analysis",
    "panel.expert.system",
    "panel.expert.research_need",
    "expertgranskning.word.moderator.batch",
    "expertgranskning.word.expert.comment",
    "expertgranskning.word.actor_context.known",
)


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
        field = _field(key)
        defaults = field["defaults"]
        _update_defaults(
            conn,
            key,
            sv=defaults["sv"],
            en=defaults["en"],
            nb=defaults["nb"],
        )


def downgrade() -> None:
    # Prompt defaults live in prompt_catalog; a downgrade restores the previous
    # revision by re-running that revision's upgrade on these keys only if needed.
    return
