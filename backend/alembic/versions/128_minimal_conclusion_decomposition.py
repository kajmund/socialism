"""decomposition asks for the smallest set of conclusions

Revision ID: 128_minimal_conclusion_decomposition
Revises: 127_decomposition_knowledge_goals
Create Date: 2026-09-27

A composite question splits into independently groundable conclusions.
A mapping of many objects under one criterion stays one research need.
Only rows that still have the previous default are updated.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "128_minimal_conclusion_decomposition"
down_revision: str | Sequence[str] | None = "127_decomposition_knowledge_goals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "research.decomposition.system"
_OLD_SV = (
    "Dela en sammansatt fråga i barn som var och en är ett självständigt "
    "kunskapsmål. Dela inte efter plural, listor, exempel, källor, "
    "observationer, faktorer eller tabeller som tillsammans besvarar samma "
    "mål. Varje barn ska kunna researchas och besvaras separat, och barnens "
    "svar ska tillsammans besvara föräldern. Upprepa inte föräldern."
)
_NEW_SV = (
    "Skapa den minsta mängd barnfrågor vars grundade svar räcker för att "
    "syntetisera ett robust svar på föräldern. Varje barn ska vara en "
    "självständigt researchbar slutsats. Dela inte efter dokument, enskilda "
    "källor, exempel eller grammatiska konjunktioner, och dela inte en "
    "kartläggning där flera objekt faller under samma kriterium. Skriv inte "
    "om föräldern. Föredra få starka barn framför många små."
)
_OLD_EN = (
    "Split a composite question into children that are each an independent "
    "knowledge goal. Do not split on plurals, lists, examples, sources, "
    "observations, factors, or tables that together answer the same goal. "
    "Each child must be researchable and answerable on its own, and the child "
    "answers together must answer the parent. Do not repeat the parent."
)
_NEW_EN = (
    "Create the smallest set of child questions whose grounded answers are "
    "sufficient to synthesize a robust answer to the parent. Each child must "
    "be an independently researchable conclusion. Do not split by document, "
    "individual source, example, or grammatical conjunction, and do not split "
    "a mapping whose objects fall under one criterion. Do not paraphrase the "
    "parent. Prefer a few strong children over many small ones."
)


def _replace_field(column: str, old: str, new: str) -> None:
    op.execute(
        sa.text(
            f"UPDATE prompt_fields SET {column} = :new WHERE key = :key AND {column} = :old"
        ).bindparams(key=_KEY, old=old, new=new)
    )


def upgrade() -> None:
    _replace_field("default_sv", _OLD_SV, _NEW_SV)
    _replace_field("default_en", _OLD_EN, _NEW_EN)
    _replace_field("default_nb", _OLD_SV, _NEW_SV)


def downgrade() -> None:
    _replace_field("default_sv", _NEW_SV, _OLD_SV)
    _replace_field("default_en", _NEW_EN, _OLD_EN)
    _replace_field("default_nb", _NEW_SV, _OLD_SV)
