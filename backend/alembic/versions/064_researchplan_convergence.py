"""Update persisted panel.moderator.research_plan defaults.

Revision ID: 064_researchplan_convergence
Revises: 063_panel_competency_state
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "064_researchplan_convergence"
down_revision: Union[str, Sequence[str], None] = "063_panel_competency_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "panel.moderator.research_plan"

_OLD_SV = (
    "Ämne: {topic}\n\n"
    "Bakgrund:\n{brief}\n\n"
    "Din öppning:\n{opening}\n\n"
    "Expertförslag (gruppera med proposal_id — sätt inte requested_by):\n"
    "{expert_proposals}\n\n"
    "Tillåtna källtyper (välj typ, inte en konkret tjänst eller server):\n"
    "{source_types}\n\n"
    "Konsolidera en researchplan inför expertbedömningen.\n\n"
    "Regler:\n"
    "- Slå ihop semantiskt överlappande frågor till ett behov. "
    "Tre varianter av samma fråga ska bli ett behov med alla relevanta proposal_ids.\n"
    "- Bevara substantiella skillnader.\n"
    "- Gör frågorna konkreta och researchbara.\n"
    "- Gruppera med proposal_ids. Sätt inte requested_by och inte permanenta id:n; "
    "requested_by härleds i kod från förslagens slot_id.\n"
    "- Välj den mest auktoritativa källtypen. Använd web sparsamt — "
    "web är inte default och ska inte fyllas i bara för att en källtyp saknas.\n"
    "- Ta bort irrelevanta eller spekulativa behov.\n"
    "- Prioritera nödvändigt framför nice-to-know.\n"
    "- Missing expertise är inte ett researchbehov. "
    "Behåll inte domänspecifika frågor från experter som saknar kompetens.\n"
    "- Skapa inte nya behov utan stöd från expertförslagen, utöver normal "
    "deduplicering och precisering.\n"
    "- Ange källtyp, inte konkret tjänst (inte lagen.nu eller en MCP-server).\n"
    "- Tom plan är giltig om inget nödvändigt återstår, "
    "eller om ingen expert har relevant domänkompetens."
)
_OLD_EN = (
    "Topic: {topic}\n\n"
    "Background:\n{brief}\n\n"
    "Your opening:\n{opening}\n\n"
    "Expert proposals (group with proposal_id — do not set requested_by):\n"
    "{expert_proposals}\n\n"
    "Allowed source types (choose a type, not a concrete service or server):\n"
    "{source_types}\n\n"
    "Consolidate a research plan before expert assessment.\n\n"
    "Rules:\n"
    "- Merge semantically overlapping questions into one need. "
    "Three variants of the same question must become one need with all relevant proposal_ids.\n"
    "- Preserve substantive differences.\n"
    "- Make the questions concrete and researchable.\n"
    "- Group with proposal_ids. Do not set requested_by or permanent ids; "
    "requested_by is derived in code from each proposal's slot_id.\n"
    "- Choose the most authoritative source type. Use web sparingly — "
    "web is not the default and must not be filled in just because a type is missing.\n"
    "- Drop irrelevant or speculative needs.\n"
    "- Prioritize necessary over nice-to-know.\n"
    "- Missing expertise is not a research need. "
    "Do not keep domain-specific questions from experts who lack competence.\n"
    "- Do not create new needs without support from the expert proposals, "
    "beyond ordinary deduplication and sharpening.\n"
    "- Suggest a source type, not a concrete service (not lagen.nu or an MCP server).\n"
    "- An empty plan is valid if nothing necessary remains, "
    "or if no expert has relevant domain competence."
)


def _defaults() -> dict[str, str]:
    return next(row for row in PROMPT_FIELDS if row["key"] == _KEY)["defaults"]


def _update_defaults(*, sv: str, en: str, nb: str) -> None:
    op.execute(
        sa.text(
            "UPDATE prompt_fields "
            "SET default_sv = :sv, default_en = :en, default_nb = :nb "
            "WHERE key = :key"
        ).bindparams(sv=sv, en=en, nb=nb, key=_KEY)
    )


def upgrade() -> None:
    defaults = _defaults()
    _update_defaults(sv=defaults["sv"], en=defaults["en"], nb=defaults["nb"])


def downgrade() -> None:
    _update_defaults(sv=_OLD_SV, en=_OLD_EN, nb=_OLD_SV)
