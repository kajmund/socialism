"""Add Norwegian (nb) SSR anchor sets and backfill configuration anchor_sets.

Revision ID: 017_ssr_anchor_nb_locale
Revises: 016_ssr_anchor_library
Create Date: 2026-08-08
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_ssr_anchor_nb_locale"
down_revision: Union[str, Sequence[str], None] = "016_ssr_anchor_library"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NB_TONE = {
    "name": "tone_nb",
    "kind": "tone",
    "locale": "nb",
    "version": "v1",
    "labels": [
        "Sterkt negativ",
        "Noe negativ",
        "Nøytral",
        "Noe positiv",
        "Sterkt positiv",
    ],
    "statements": [
        "Teksten uttrykker sterkt negativ, kritisk eller resignert holdning til budskapet.",
        "Teksten heller mot negativ eller skeptisk tone, men uten total avvisning.",
        "Teksten er nøytral, usikker eller mangler tydelig vurdering av budskapet.",
        "Teksten heller mot positiv, konstruktiv eller håpefull tone.",
        "Teksten uttrykker sterkt positiv, støttende eller entusiastisk mottakelse.",
    ],
}

_NB_STYLE = {
    "name": "style_nb",
    "kind": "style",
    "locale": "nb",
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
        "Sarkastisk eller ironisk tone med konkret kritikk, ofte med tall eller skarp observasjon.",
        "Resignert eller trett tone med hverdagsmetaforer om hvordan ting lekker eller ikke fungerer.",
        "Faktadrevet og autoritetsbasert stil som viser til kilder, forskning eller data.",
        "Personlig og hjertelig fortelling med egne erfaringer eller følelser.",
        "Optimistisk og løsningsfokusert stil som peker fremover og mot felles løsninger.",
        "Provoserende eller konfronterende språk som anklager, skammer ut eller eskalerer konflikten.",
    ],
}


def upgrade() -> None:
    conn = op.get_bind()
    ids: dict[tuple[str, str], int] = {}

    for row in (_NB_TONE, _NB_STYLE):
        existing = conn.execute(
            sa.text(
                "SELECT id FROM ssr_anchor_sets "
                "WHERE kind = :kind AND locale = :locale AND status = 'published' "
                "ORDER BY id ASC LIMIT 1"
            ),
            {"kind": row["kind"], "locale": row["locale"]},
        ).fetchone()
        if existing:
            ids[(row["kind"], row["locale"])] = int(existing[0])
            continue
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
        ids[(row["kind"], row["locale"])] = int(result.lastrowid)

    nb_ref = {"tone": ids[("tone", "nb")], "style": ids[("style", "nb")]}

    configs = conn.execute(sa.text("SELECT id, anchor_sets FROM configurations")).fetchall()
    for config_id, anchor_sets_raw in configs:
        refs = json.loads(anchor_sets_raw) if anchor_sets_raw else {}
        if isinstance(refs.get("nb"), dict) and refs["nb"].get("tone") and refs["nb"].get("style"):
            continue
        refs["nb"] = nb_ref
        conn.execute(
            sa.text("UPDATE configurations SET anchor_sets = :refs WHERE id = :id"),
            {"refs": json.dumps(refs), "id": config_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM ssr_anchor_sets WHERE locale = 'nb'"),
    )
    configs = conn.execute(sa.text("SELECT id, anchor_sets FROM configurations")).fetchall()
    for config_id, anchor_sets_raw in configs:
        refs = json.loads(anchor_sets_raw) if anchor_sets_raw else {}
        if "nb" in refs:
            del refs["nb"]
            conn.execute(
                sa.text("UPDATE configurations SET anchor_sets = :refs WHERE id = :id"),
                {"refs": json.dumps(refs), "id": config_id},
            )
