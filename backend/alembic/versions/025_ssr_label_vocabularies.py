"""ssr_label_vocabularies — global tone/style label vocabulary.

Revision ID: 025_ssr_label_vocabularies
Revises: 024_spindoctor_messages
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025_ssr_label_vocabularies"
down_revision: Union[str, Sequence[str], None] = "024_spindoctor_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED: list[dict] = [
    {
        "kind": "tone",
        "locale": "sv",
        "entries": [
            {"key": "strongly_negative", "label": "Starkt negativ"},
            {"key": "somewhat_negative", "label": "Något negativ"},
            {"key": "neutral", "label": "Neutral"},
            {"key": "somewhat_positive", "label": "Något positiv"},
            {"key": "strongly_positive", "label": "Starkt positiv"},
        ],
    },
    {
        "kind": "tone",
        "locale": "en",
        "entries": [
            {"key": "strongly_negative", "label": "Strongly negative"},
            {"key": "somewhat_negative", "label": "Somewhat negative"},
            {"key": "neutral", "label": "Neutral"},
            {"key": "somewhat_positive", "label": "Somewhat positive"},
            {"key": "strongly_positive", "label": "Strongly positive"},
        ],
    },
    {
        "kind": "style",
        "locale": "sv",
        "entries": [
            {"key": "sarcastic_concrete", "label": "Sarkastisk + konkret kritik"},
            {"key": "resigned_metaphor", "label": "Uppgiven + vardagsmetafor"},
            {"key": "facts_authority", "label": "Fakta + yrkesauktoritet"},
            {"key": "personal_heartfelt", "label": "Personlig + hjärtlig berättelse"},
            {"key": "optimistic_solution", "label": "Optimistisk / lösningsfokuserad"},
            {
                "key": "provocative_confrontational",
                "label": "Provocerande / konfronterande",
            },
        ],
    },
    {
        "kind": "style",
        "locale": "en",
        "entries": [
            {"key": "sarcastic_concrete", "label": "Sarkastisk + konkret kritik"},
            {"key": "resigned_metaphor", "label": "Uppgiven + vardagsmetafor"},
            {"key": "facts_authority", "label": "Fakta + yrkesauktoritet"},
            {"key": "personal_heartfelt", "label": "Personlig + hjärtlig berättelse"},
            {"key": "optimistic_solution", "label": "Optimistisk / lösningsfokuserad"},
            {
                "key": "provocative_confrontational",
                "label": "Provocerande / konfronterande",
            },
        ],
    },
]


def upgrade() -> None:
    op.create_table(
        "ssr_label_vocabularies",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("kind", "locale"),
    )

    conn = op.get_bind()
    for row in _SEED:
        conn.execute(
            sa.text(
                "INSERT INTO ssr_label_vocabularies (kind, locale, entries) "
                "VALUES (:kind, :locale, :entries)"
            ),
            {
                "kind": row["kind"],
                "locale": row["locale"],
                "entries": json.dumps(row["entries"], ensure_ascii=False),
            },
        )


def downgrade() -> None:
    op.drop_table("ssr_label_vocabularies")
