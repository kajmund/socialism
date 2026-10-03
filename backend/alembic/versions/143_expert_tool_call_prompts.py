"""Tell expert chat to call tools instead of describing the call.

Revision ID: 143_expert_tool_call_prompts
Revises: 142_drop_graph_revalidation_queues
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "143_expert_tool_call_prompts"
down_revision: str | Sequence[str] | None = "142_drop_graph_revalidation_queues"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Earlier stored defaults. Norwegian copies Swedish for these keys.
# consult_tool has two: the catalog text and the shorter row still in databases.
_PREVIOUS: dict[str, list[dict[str, str]]] = {
    "chat.mode.interview": [
        {
            "sv": (
                "Läge: INTERVJU. En analytiker intervjuar dig. Svara i första person "
                "som personan. Var kort (1–4 meningar), konkret, och håll dig till din "
                "bakgrund. Hitta inte på statistik du inte skulle kunna. Svara på svenska."
            ),
            "en": (
                "Mode: INTERVIEW. An analyst interviews you. Answer in first person as "
                "the persona. Be short (1–4 sentences), concrete, and stay within your "
                "background. Do not invent statistics you would not know. Answer in English."
            ),
        }
    ],
    "chat.expert.consult_tool": [
        {
            "sv": (
                "Om användarens fråga ligger utanför ditt eget kompetensområde ska du "
                "anropa ask_expert med en fristående och tydligt omformulerad fråga. "
                "Att skriva att du skickar frågan räcker inte — utan verktygsanropet "
                "når den aldrig kollegan. Använd inte verktyget när du själv har "
                "relevant kompetens. Gissa inte och visa aldrig verktygsanropet."
            ),
            "en": (
                "When the user's question is outside your own professional competence, "
                "call ask_expert with a clear, standalone reformulation. Saying that you "
                "will send the question does not send it. Do not use the tool when you "
                "have relevant competence. Do not guess or reveal tool calls."
            ),
        },
        {
            "sv": (
                "Om användarens fråga ligger utanför ditt eget kompetensområde ska du "
                "använda ask_expert med en fristående och tydligt omformulerad fråga. "
                "Använd inte verktyget när du själv har relevant kompetens. "
                "Gissa inte och visa aldrig verktygsanropet."
            ),
            "en": (
                "When the user's question is outside your own professional competence, "
                "use ask_expert with a clear, standalone reformulation. Do not use the "
                "tool when you have relevant competence. Do not guess or reveal tool calls."
            ),
        },
    ],
    "chat.expert.company_tools": [
        {
            "sv": (
                "Du har bolagsverktyg: search_companies och lookup_company. "
                "Använd dem bara när du saknar organisationsnummer, omsättning, resultat, "
                "anställda, styrelse, F-skatt/moms, koncern, varumärken eller "
                "registreringsdatum. Slå inte upp siffror du redan har fått. "
                "Hitta inte på nyckeltal. "
                "Svara fortfarande i första person som experten. Visa aldrig tool-anrop."
            ),
            "en": (
                "You have company tools: search_companies and lookup_company. "
                "Use them only when you lack an organization number, revenue, profit/loss, "
                "employees, board, F-tax/VAT, group, trademarks, or registration date. "
                "Do not look up figures you already have. "
                "Do not invent figures. "
                "Still answer in first person as the expert. Never expose tool calls."
            ),
        }
    ],
    "chat.expert.search_tools": [
        {
            "sv": (
                "Du har samma sökverktyg som politik-personas: search_duckduckgo "
                "(nyheter, lagar, avtal) och search_wiki (korta namn/begrepp, "
                "aldrig långa nyhetsfrågor). Sök inte efter nyckeltal du redan har fått "
                "(omsättning, resultat, anställda, org.nr). "
                "Gissa inte. Visa aldrig tool-anrop."
            ),
            "en": (
                "You have the same search tools as political personas: "
                "search_duckduckgo (news, laws, contracts) and search_wiki "
                "(short names/terms, never long news queries). Do not search for "
                "figures you already have (revenue, profit/loss, employees, org. no.). "
                "Do not guess. Never expose tool calls."
            ),
        }
    ],
}


def _field(key: str) -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == key)


def _apply(conn, key: str, *, source: dict[str, str], target: dict[str, str]) -> None:
    for language, column in (
        ("sv", "default_sv"),
        ("en", "default_en"),
        ("nb", "default_nb"),
    ):
        old = source["sv"] if language == "nb" else source[language]
        new = target["sv"] if language == "nb" else target[language]
        conn.execute(
            sa.text(
                f"UPDATE prompt_fields SET {column} = :new "
                f"WHERE key = :key AND {column} = :old"
            ).bindparams(key=key, old=old, new=new)
        )
        conn.execute(
            sa.text(
                "UPDATE prompt_overrides SET text = :new "
                "WHERE language = :language AND text = :old "
                "AND prompt_field_id = (SELECT id FROM prompt_fields WHERE key = :key)"
            ).bindparams(key=key, language=language, old=old, new=new)
        )


def upgrade() -> None:
    conn = op.get_bind()
    for key, previous in _PREVIOUS.items():
        target = _field(key)["defaults"]
        for source in previous:
            _apply(conn, key, source=source, target=target)


def downgrade() -> None:
    conn = op.get_bind()
    for key, previous in _PREVIOUS.items():
        target = _field(key)["defaults"]
        _apply(conn, key, source=target, target=previous[0])
