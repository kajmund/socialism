"""SSR anchor library + configuration anchor_sets refs.

Revision ID: 016_ssr_anchor_library
Revises: 015_configuration_ssr_temperature
Create Date: 2026-08-08
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_ssr_anchor_library"
down_revision: Union[str, Sequence[str], None] = "015_configuration_ssr_temperature"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED = [
    {
        "name": "tone_sv",
        "kind": "tone",
        "locale": "sv",
        "version": "v1",
        "labels": [
            "Starkt negativ",
            "Något negativ",
            "Neutral",
            "Något positiv",
            "Starkt positiv",
        ],
        "statements": [
            "Texten uttrycker starkt negativ, kritisk eller uppgiven hållning till budskapet.",
            "Texten lutar åt negativ eller skeptisk ton, men utan total avfärdning.",
            "Texten är neutral, obeslutsam eller saknar tydlig värdering av budskapet.",
            "Texten lutar åt positiv, konstruktiv eller hoppfull ton.",
            "Texten uttrycker starkt positivt, stöttande eller entusiastiskt mottagande.",
        ],
    },
    {
        "name": "tone_en",
        "kind": "tone",
        "locale": "en",
        "version": "v1",
        "labels": [
            "Strongly negative",
            "Somewhat negative",
            "Neutral",
            "Somewhat positive",
            "Strongly positive",
        ],
        "statements": [
            "The text expresses a strongly negative, critical, or resigned stance toward the message.",
            "The text leans negative or skeptical, but without total rejection.",
            "The text is neutral, undecided, or lacks a clear evaluation of the message.",
            "The text leans positive, constructive, or hopeful.",
            "The text expresses strongly positive, supportive, or enthusiastic reception.",
        ],
    },
    {
        "name": "style_sv",
        "kind": "style",
        "locale": "sv",
        "version": "v1",
        "labels": [
            "Sarkastisk + konkret kritik",
            "Uppgiven + vardagsmetafor",
            "Fakta + yrkesauktoritet",
            "Personlig + hjärtlig berättelse",
            "Optimistisk / lösningsfokuserad",
            "Provocerande / konfronterande",
        ],
        "statements": [
            "Sarkastisk eller ironisk ton med konkret kritik, ofta med siffror eller skarp iakttagelse.",
            "Uppgiven eller trött ton med vardagsmetaforer om hur saker läcker eller inte fungerar.",
            "Faktadriven och auktoritetsbaserad stil som hänvisar till källor, forskning eller data.",
            "Personlig och hjärtlig berättelse med egna erfarenheter eller känslor.",
            "Optimistisk och lösningsfokuserad stil som pekar framåt och mot gemensamma lösningar.",
            "Provocerande eller konfronterande språk som anklagar, skäms ut eller eskalerar konflikten.",
        ],
    },
    {
        "name": "style_en",
        "kind": "style",
        "locale": "en",
        "version": "v1",
        "labels": [
            "Sarkastisk + konkret kritik",
            "Uppgiven + vardagsmetafor",
            "Fakta + yrkesauktoritet",
            "Personlig + hjärtlig berättelse",
            "Optimistisk / lösningsfokuserad",
            "Provocerande / konfronterande",
        ],
        "statements": [
            "Sarcastic or ironic tone with concrete criticism, often with numbers or sharp observation.",
            "Resigned or weary tone with everyday metaphors about things leaking or not working.",
            "Fact-driven, authority-based style that cites sources, research, or data.",
            "Personal and warm storytelling with lived experience or feelings.",
            "Optimistic, solution-focused style that looks forward and toward joint solutions.",
            "Provocative or confrontational language that blames, shames, or escalates conflict.",
        ],
    },
]


def upgrade() -> None:
    op.create_table(
        "ssr_anchor_sets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("statements", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ssr_anchor_sets_kind", "ssr_anchor_sets", ["kind"])
    op.create_index("ix_ssr_anchor_sets_locale", "ssr_anchor_sets", ["locale"])
    op.create_index("ix_ssr_anchor_sets_status", "ssr_anchor_sets", ["status"])

    op.create_table(
        "ssr_anchor_calibration_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("anchor_set_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("human_label", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["anchor_set_id"], ["ssr_anchor_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ssr_anchor_calibration_items_anchor_set_id",
        "ssr_anchor_calibration_items",
        ["anchor_set_id"],
    )

    op.add_column(
        "configurations",
        sa.Column("anchor_sets", sa.JSON(), nullable=False, server_default="{}"),
    )

    conn = op.get_bind()
    ids: dict[tuple[str, str], int] = {}
    for row in _SEED:
        result = conn.execute(
            sa.text(
                "INSERT INTO ssr_anchor_sets "
                "(name, kind, locale, version, labels, statements, status) "
                "VALUES (:name, :kind, :locale, :version, :labels, :statements, 'published')"
            ),
            {
                **row,
                "labels": json.dumps(row["labels"]),
                "statements": json.dumps(row["statements"]),
            },
        )
        anchor_id = result.lastrowid
        ids[(row["kind"], row["locale"])] = int(anchor_id)

    refs = {
        "sv": {"tone": ids[("tone", "sv")], "style": ids[("style", "sv")]},
        "en": {"tone": ids[("tone", "en")], "style": ids[("style", "en")]},
    }
    conn.execute(
        sa.text("UPDATE configurations SET anchor_sets = :refs"),
        {"refs": json.dumps(refs)},
    )


def downgrade() -> None:
    op.drop_column("configurations", "anchor_sets")
    op.drop_index("ix_ssr_anchor_calibration_items_anchor_set_id", table_name="ssr_anchor_calibration_items")
    op.drop_table("ssr_anchor_calibration_items")
    op.drop_index("ix_ssr_anchor_sets_status", table_name="ssr_anchor_sets")
    op.drop_index("ix_ssr_anchor_sets_locale", table_name="ssr_anchor_sets")
    op.drop_index("ix_ssr_anchor_sets_kind", table_name="ssr_anchor_sets")
    op.drop_table("ssr_anchor_sets")
