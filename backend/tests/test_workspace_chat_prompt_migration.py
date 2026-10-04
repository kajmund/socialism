"""Existing workspace chats receive document access without replacing customer prompts."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.services.prompt_catalog import PROMPT_FIELDS


@pytest.fixture
def document_prompt_migration(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/152_workspace_chat_documents.py"
    spec = importlib.util.spec_from_file_location("workspace_document_prompt_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE prompt_fields (id INTEGER PRIMARY KEY, key TEXT UNIQUE, "
                "default_sv TEXT, default_en TEXT, default_nb TEXT, modules JSON, "
                "section TEXT, label_sv TEXT, label_en TEXT, hint_sv TEXT, hint_en TEXT, "
                "active BOOLEAN, llm_selection_mode TEXT, llm_configuration_id INTEGER)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE prompt_overrides (prompt_field_id INTEGER, customer_id INTEGER, "
                "language TEXT, text TEXT)"
            )
        )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        yield migration, connection
    engine.dispose()


def _defaults(connection, key: str) -> tuple[str, str, str]:
    return tuple(
        connection.execute(
            sa.text("SELECT default_sv,default_en,default_nb FROM prompt_fields WHERE key=:key"),
            {"key": key},
        ).one()
    )


def _overrides(connection) -> list[tuple]:
    return [
        tuple(row)
        for row in connection.execute(
            sa.text(
                "SELECT prompt_field_id,customer_id,language,text FROM prompt_overrides "
                "ORDER BY prompt_field_id,customer_id,language"
            )
        )
    ]


@pytest.mark.parametrize("custom_language", ["sv", "en", "nb"])
@pytest.mark.parametrize("key", [
    "chat.workspace.system",
    "workspace.voice.system",
    "workspace.voice.tool.get_workspace_context",
    "workspace.voice.tool.ingest_source",
])
def test_document_inventory_upgrade_preserves_custom_prompts_and_reverses_defaults(
    document_prompt_migration, custom_language, key,
):
    migration, connection = document_prompt_migration
    old = migration._OLD if key == migration._KEY else migration._VOICE_OLD[key]
    new = migration._NEW if key == migration._KEY else migration._VOICE_NEW[key]
    defaults = next(
        field["defaults"]
        for field in PROMPT_FIELDS
        if field["key"] == key
    )
    assert defaults == new
    original = {**old, custom_language: "customer default"}
    connection.execute(
        sa.text("INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) "
                "VALUES (1,:key,:sv,:en,:nb)"),
        {"key": key, **original},
    )
    connection.execute(
        sa.text("INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) "
                "VALUES (2,'other',:sv,:en,:nb)"),
        old,
    )
    for language in ("sv", "en", "nb"):
        connection.execute(
            sa.text("INSERT INTO prompt_overrides VALUES (:field,:customer,:language,:text)"),
            [
                {"field": 1, "customer": 1, "language": language, "text": old[language]},
                {"field": 1, "customer": 2, "language": language, "text": "customer override"},
                {"field": 2, "customer": 1, "language": language, "text": old[language]},
            ],
        )
    before_overrides = _overrides(connection)

    migration.upgrade()
    migration.upgrade()
    assert _defaults(connection, key) == tuple(
        "customer default" if language == custom_language else defaults[language]
        for language in ("sv", "en", "nb")
    )
    assert _defaults(connection, "other") == tuple(old.values())
    assert _overrides(connection) == [
        (field, customer, language, defaults[language] if field == customer == 1 else text)
        for field, customer, language, text in before_overrides
    ]

    migration.downgrade()
    migration.downgrade()
    assert _defaults(connection, key) == tuple(original.values())
    assert _defaults(connection, "other") == tuple(old.values())
    assert _overrides(connection) == before_overrides


def test_argument_transport_prompt_seed_is_frozen_idempotent_and_reversible(document_prompt_migration):
    migration, connection = document_prompt_migration
    catalog = next(field for field in PROMPT_FIELDS if field["key"] == migration._ARGUMENT_KEY)
    assert catalog["defaults"] == {
        language: migration._ARGUMENT_FIELD[f"default_{language}"]
        for language in ("sv", "en", "nb")
    }
    migration.upgrade()
    migration.upgrade()
    assert connection.scalar(sa.text("SELECT COUNT(*) FROM prompt_fields")) == 1
    assert _defaults(connection, migration._ARGUMENT_KEY) == tuple(catalog["defaults"].values())
    migration.downgrade()
    migration.downgrade()
    assert connection.scalar(sa.text("SELECT COUNT(*) FROM prompt_fields")) == 0


@pytest.mark.parametrize("change", ["default_sv", "label_sv", "active", "override"])
def test_argument_transport_downgrade_preserves_customized_field(document_prompt_migration, change):
    migration, connection = document_prompt_migration
    migration.upgrade()
    if change == "override":
        connection.execute(sa.text(
            "INSERT INTO prompt_overrides (prompt_field_id,customer_id,language,text) "
            "SELECT id,1,'sv','customer override' FROM prompt_fields WHERE key=:key"
        ), {"key": migration._ARGUMENT_KEY})
    else:
        connection.execute(sa.text(f"UPDATE prompt_fields SET {change}=:value WHERE key=:key"),
                           {"value": False if change == "active" else "customer setting",
                            "key": migration._ARGUMENT_KEY})
    before = connection.execute(sa.text("SELECT * FROM prompt_fields")).one()
    migration.upgrade()
    migration.downgrade()
    assert connection.execute(sa.text("SELECT * FROM prompt_fields")).one() == before
    if change == "override":
        assert _overrides(connection)[0][-1] == "customer override"
