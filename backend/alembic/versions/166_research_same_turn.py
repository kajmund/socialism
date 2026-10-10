"""Let expert research start in the same turn as the question."""

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision = "166_research_same_turn"
down_revision = "165_workspace_smalltalk_no_tools"
branch_labels = None
depends_on = None

_RESEARCH_KEY = "chat.expert.research_tool"
_VOICE_KEY = "workspace.voice.system"
_RESEARCH_OLD = {
    "sv": (
        "Du har verktyget start_research för att köa research i bakgrunden. "
        "Du får ALDRIG anropa verktyget direkt när ett kunskapsgap upptäcks. "
        "Fråga först uttryckligen användaren om du ska starta research och förklara "
        "kort vilken fråga som ska undersökas. Anropa verktyget först i ett senare "
        "svar när användaren uttryckligen har bekräftat. Skicka en fristående, "
        "generell och researchbar fråga som argumentet question. Verktyget köar "
        "arbetet; påstå inte att resultatet redan finns."
    ),
    "en": (
        "You have the start_research tool for queueing background research. NEVER "
        "call it immediately when a knowledge gap is found. First explicitly ask "
        "the user whether research should be started and briefly state the question "
        "to investigate. Call the tool only in a later response after the user has "
        "explicitly confirmed. Pass a standalone, general, researchable question in "
        "the question argument. The tool only queues work; do not claim results exist."
    ),
}
_VOICE_OLD = {
    "sv": (
        "start_research kräver fortfarande ett erbjudande och ett uttryckligt "
        "bekräftande svar i en senare användartur."
    ),
    "en": (
        "start_research still requires an offer and an explicit confirming reply "
        "in a later user turn."
    ),
}
_VOICE_NEW = {
    "sv": (
        "När research behövs anropar du start_research i samma svar och frågar "
        "inte om ett separat bekräftande svar."
    ),
    "en": (
        "When research is needed, call start_research in the same reply and do "
        "not ask for a separate confirming reply."
    ),
}


def _catalog(key: str) -> dict[str, str]:
    for field in PROMPT_FIELDS:
        if field["key"] == key:
            return field["defaults"]
    raise RuntimeError(f"missing prompt catalog field {key}")


def _replace_default(key: str, language: str, old: str, new: str) -> None:
    column = f"default_{language}"
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"UPDATE prompt_fields SET {column} = replace({column}, :old, :new) "
            "WHERE key = :key"
        ),
        {"key": key, "old": old, "new": new},
    )
    connection.execute(
        sa.text(
            "UPDATE prompt_overrides SET text = replace(text, :old, :new) "
            "WHERE language = :language AND prompt_field_id = "
            "(SELECT id FROM prompt_fields WHERE key = :key)"
        ),
        {"key": key, "language": language, "old": old, "new": new},
    )


def upgrade() -> None:
    research = _catalog(_RESEARCH_KEY)
    _RESEARCH_OLD["nb"] = _RESEARCH_OLD["sv"]
    for language in ("sv", "en", "nb"):
        _replace_default(_RESEARCH_KEY, language, _RESEARCH_OLD[language], research[language])
    _VOICE_OLD["nb"] = _VOICE_OLD["sv"]
    _VOICE_NEW["nb"] = _VOICE_NEW["sv"]
    for language in ("sv", "en", "nb"):
        _replace_default(_VOICE_KEY, language, _VOICE_OLD[language], _VOICE_NEW[language])


def downgrade() -> None:
    research = _catalog(_RESEARCH_KEY)
    _RESEARCH_OLD["nb"] = _RESEARCH_OLD["sv"]
    for language in ("sv", "en", "nb"):
        _replace_default(_RESEARCH_KEY, language, research[language], _RESEARCH_OLD[language])
    _VOICE_OLD["nb"] = _VOICE_OLD["sv"]
    _VOICE_NEW["nb"] = _VOICE_NEW["sv"]
    for language in ("sv", "en", "nb"):
        _replace_default(_VOICE_KEY, language, _VOICE_NEW[language], _VOICE_OLD[language])
