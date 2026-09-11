"""Add research-plan repair prompt and require executable source types.

Revision ID: 067_researchplan_valid_proposals
Revises: 066_researchplan_convergence
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "067_researchplan_valid_proposals"
down_revision: Union[str, Sequence[str], None] = "066_researchplan_convergence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_KEY = "panel.moderator.research_plan_repair"
_UPDATE_KEY = "panel.expert.research_need"

_OLD_EXPERT_SV = (
    "Ämne: {topic}\n\n"
    "Bakgrund:\n{brief}\n\n"
    "Moderatorns öppning:\n{opening}\n\n"
    "Din profil:\n{profile}\n\n"
    "Tillåtna källtyper (ange typ, inte en konkret tjänst eller server):\n"
    "{source_types}\n\n"
    "Vilka fakta, källor eller underlag behöver du innan du kan göra en "
    "välgrundad bedömning?\n\n"
    "Först avgör om din profil faktiskt täcker ämnet och moderatorns fråga.\n"
    "has_domain_competence = true BARA om du har faktisk domänkompetens att "
    "göra en substantiell expertbedömning av just den här frågan. "
    "Analogier, allmän orientering, metodperspektiv eller att rekommendera "
    "en annan expert är inte kompetens.\n"
    "Om kompetensen saknas: has_domain_competence = false, needs måste vara tom, "
    "och competence_reason ska vara missing expertise / requires domain expert. "
    "Formulera inte domänspecifika researchfrågor (lagrum, praxis, förarbeten "
    "eller motsvarande) som om du behärskade området.\n\n"
    "Regler:\n"
    "- Identifiera bara information som faktiskt behövs för din bedömning.\n"
    "- Fråga inte efter sådant som redan tydligt finns i briefen eller öppningen.\n"
    "- Formulera researchbara frågor.\n"
    "- Skilj faktafrågor från rättsfrågor.\n"
    "- Föreslå källtyp, inte en specifik tjänst (inte lagen.nu eller en MCP-server).\n"
    "- Undvik nice-to-know.\n"
    "- Gör inte slutbedömningen här.\n"
    "- Noll behov är ett giltigt svar om underlaget räcker.\n"
    "- web är tillåten men inte default."
)
_OLD_EXPERT_EN = (
    "Topic: {topic}\n\n"
    "Background:\n{brief}\n\n"
    "Moderator opening:\n{opening}\n\n"
    "Your profile:\n{profile}\n\n"
    "Allowed source types (name a type, not a concrete service or server):\n"
    "{source_types}\n\n"
    "Which facts, sources, or supporting material do you need before you can "
    "make a well-founded assessment?\n\n"
    "First decide whether your profile actually covers the topic and the "
    "moderator's question.\n"
    "has_domain_competence = true ONLY if you have actual domain competence to "
    "make a substantial expert assessment of this exact question. "
    "Analogies, general orientation, a method perspective, or recommending "
    "another expert are not competence.\n"
    "If competence is missing: has_domain_competence = false, needs must be empty, "
    "and competence_reason should be missing expertise / requires domain expert. "
    "Do not write domain-specific research questions (statutes, case law, "
    "preparatory works, or similar) as if you mastered the area.\n\n"
    "Rules:\n"
    "- Identify only information actually needed for your assessment.\n"
    "- Do not ask for something already clearly present in the brief or opening.\n"
    "- Phrase researchable questions.\n"
    "- Separate questions of fact from questions of law.\n"
    "- Suggest a source type, not a specific service (not lagen.nu or an MCP server).\n"
    "- Avoid nice-to-know.\n"
    "- Do not make the final assessment here.\n"
    "- Zero needs is a valid answer if the brief is enough.\n"
    "- web is allowed but is not the default."
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
    defaults = _field(_UPDATE_KEY)["defaults"]
    _update_defaults(
        conn,
        _UPDATE_KEY,
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
            modules=json.dumps(modules_for_prompt_key(_NEW_KEY)),
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
    _update_defaults(conn, _UPDATE_KEY, sv=_OLD_EXPERT_SV, en=_OLD_EXPERT_EN, nb=_OLD_EXPERT_SV)
    field_id = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
    ).fetchone()
    if field_id is None:
        return
    conn.execute(
        sa.text(
            "DELETE FROM prompt_overrides WHERE prompt_field_id = :field_id"
        ).bindparams(field_id=field_id[0])
    )
    conn.execute(
        sa.text("DELETE FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
    )
