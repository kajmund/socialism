"""Add rewrite-suggestion columns and update Word paragraph prompt.

Revision ID: 053_word_rewrite_suggestion
Revises: 052_expertgranskning_results
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "053_word_rewrite_suggestion"
down_revision: Union[str, Sequence[str], None] = "052_expertgranskning_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_PARAGRAPH_SV = (
    "Du modererar en expertpanel som granskar ett Word-dokument stycke för stycke. "
    "Ingen poängsättning. Skriv bara kommentarer som en expert faktiskt skulle fästa "
    "vid stycket. Hoppa över experter som inte har något att tillföra.\n\n"
    "Experter:\n{expert_list}\n\n"
    "Avsnitt: {section_heading}\n"
    "Word-stil: {style}\n\n"
    "Stycke:\n{paragraph_text}\n\n"
    "Returnera en lista comments med expert_id, expert_namn och kommentar. "
    "Listan får vara tom."
)
_OLD_PARAGRAPH_EN = (
    "You moderate an expert panel reviewing a Word document paragraph by paragraph. "
    "No scoring. Only write comments an expert would actually attach to the paragraph. "
    "Skip experts who have nothing to add.\n\n"
    "Experts:\n{expert_list}\n\n"
    "Section: {section_heading}\n"
    "Word style: {style}\n\n"
    "Paragraph:\n{paragraph_text}\n\n"
    "Return a comments list with expert_id, expert_namn, and kommentar. "
    "The list may be empty."
)


def _paragraph_defaults() -> dict[str, str]:
    field = next(row for row in PROMPT_FIELDS if row["key"] == "expertgranskning.word.paragraph")
    return field["defaults"]


def upgrade() -> None:
    op.add_column(
        "expertgranskning_results",
        sa.Column(
            "is_rewrite_suggestion",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "expertgranskning_results",
        sa.Column("foreslagen_text", sa.Text(), nullable=True),
    )
    defaults = _paragraph_defaults()
    op.execute(
        sa.text(
            "UPDATE prompt_fields "
            "SET default_sv = :sv, default_en = :en, default_nb = :nb "
            "WHERE key = 'expertgranskning.word.paragraph'"
        ).bindparams(sv=defaults["sv"], en=defaults["en"], nb=defaults["nb"])
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE prompt_fields "
            "SET default_sv = :sv, default_en = :en, default_nb = :nb "
            "WHERE key = 'expertgranskning.word.paragraph'"
        ).bindparams(sv=_OLD_PARAGRAPH_SV, en=_OLD_PARAGRAPH_EN, nb=_OLD_PARAGRAPH_SV)
    )
    op.drop_column("expertgranskning_results", "foreslagen_text")
    op.drop_column("expertgranskning_results", "is_rewrite_suggestion")
