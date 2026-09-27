"""decomposition requires semantic progress

Revision ID: 129_decomposition_semantic_progress
Revises: 128_minimal_conclusion_decomposition
Create Date: 2026-09-27

A child set must separate knowledge needs. One child is not a decomposition
when it only reformulates the parent, and one dimension is not split by outcome.
Only rows that still have the previous default are updated.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "129_decomposition_semantic_progress"
down_revision: str | Sequence[str] | None = "128_minimal_conclusion_decomposition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "research.decomposition.system"
_OLD_SV = (
    "Skapa den minsta mängd barnfrågor vars grundade svar räcker för att "
    "syntetisera ett robust svar på föräldern. Varje barn ska vara en "
    "självständigt researchbar slutsats. Dela inte efter dokument, enskilda "
    "källor, exempel eller grammatiska konjunktioner, och dela inte en "
    "kartläggning där flera objekt faller under samma kriterium. Skriv inte "
    "om föräldern. Föredra få starka barn framför många små."
)
_NEW_SV = (
    "Skapa den minsta mängd barnfrågor vars grundade svar räcker för att "
    "syntetisera ett robust svar på föräldern. Varje barn ska vara ett "
    "självständigt och strikt smalare kunskapsbehov. Dela inte efter dokument, "
    "enskilda källor, exempel, evidensobjekt eller grammatiska konjunktioner, "
    "och dela inte en kartläggning där flera objekt faller under samma kriterium. "
    "Dela inte samma kunskapsdimension i positiva och negativa utfall. Ett ensamt "
    "barn är bara giltigt när det är ett separat och strikt smalare kunskapsbehov, "
    "inte en omformulering. Föredra få starka barn framför många små."
)
_OLD_EN = (
    "Create the smallest set of child questions whose grounded answers are "
    "sufficient to synthesize a robust answer to the parent. Each child must "
    "be an independently researchable conclusion. Do not split by document, "
    "individual source, example, or grammatical conjunction, and do not split "
    "a mapping whose objects fall under one criterion. Do not paraphrase the "
    "parent. Prefer a few strong children over many small ones."
)
_NEW_EN = (
    "Create the smallest set of child questions whose grounded answers are "
    "sufficient to synthesize a robust answer to the parent. Each child must "
    "be an independently researchable and strictly narrower knowledge need. "
    "Do not split by document, individual source, example, evidence object, or "
    "grammatical conjunction, and do not split a mapping whose objects fall "
    "under one criterion. Do not split one knowledge dimension into positive and "
    "negative outcomes. A single child is valid only when it is a separate and "
    "strictly narrower knowledge need, not a reformulation. Prefer a few strong "
    "children over many small ones."
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
