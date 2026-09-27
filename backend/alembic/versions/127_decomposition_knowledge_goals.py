"""decomposition splits knowledge goals, not answer items

Revision ID: 127_decomposition_knowledge_goals
Revises: 126_progress_idempotency_key
Create Date: 2026-09-27

Atomicity counts independent knowledge goals. The decomposition prompt must
not tell the generator to split a list of evidence objects into children.
Only rows that still have the previous default are updated.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "127_decomposition_knowledge_goals"
down_revision: str | Sequence[str] | None = "126_progress_idempotency_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "research.decomposition.system"
_OLD_SV = (
    "Dekomponera en sammansatt fråga i få, oberoende barnfrågor. "
    "Varje barn ska efterfråga en sammanhängande kunskapsbit som kan "
    "stödjas av avgränsad evidens. Upprepa inte föräldern."
)
_NEW_SV = (
    "Dela en sammansatt fråga i barn som var och en är ett självständigt "
    "kunskapsmål. Dela inte efter plural, listor, exempel, källor, "
    "observationer, faktorer eller tabeller som tillsammans besvarar samma "
    "mål. Varje barn ska kunna researchas och besvaras separat, och barnens "
    "svar ska tillsammans besvara föräldern. Upprepa inte föräldern."
)
_OLD_EN = (
    "Decompose a composite question into a few independent child questions. "
    "Each child must ask for one coherent piece of knowledge supportable by "
    "bounded evidence. Do not repeat the parent."
)
_NEW_EN = (
    "Split a composite question into children that are each an independent "
    "knowledge goal. Do not split on plurals, lists, examples, sources, "
    "observations, factors, or tables that together answer the same goal. "
    "Each child must be researchable and answerable on its own, and the child "
    "answers together must answer the parent. Do not repeat the parent."
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
