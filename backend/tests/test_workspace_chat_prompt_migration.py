"""Existing workspace chats receive document access without replacing customer prompts."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.services.workspace_chat_prompts import workspace_prompt_fields


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
                "default_sv TEXT, default_en TEXT, default_nb TEXT)"
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
def test_document_inventory_upgrade_preserves_custom_prompts_and_reverses_defaults(
    document_prompt_migration, custom_language,
):
    migration, connection = document_prompt_migration
    defaults = next(
        field["defaults"]
        for field in workspace_prompt_fields()
        if field["key"] == migration._KEY
    )
    assert defaults == migration._NEW
    original = {**migration._OLD, custom_language: "customer default"}
    connection.execute(
        sa.text("INSERT INTO prompt_fields VALUES (1,:key,:sv,:en,:nb)"),
        {"key": migration._KEY, **original},
    )
    connection.execute(
        sa.text("INSERT INTO prompt_fields VALUES (2,'other',:sv,:en,:nb)"),
        migration._OLD,
    )
    for language in ("sv", "en", "nb"):
        connection.execute(
            sa.text("INSERT INTO prompt_overrides VALUES (:field,:customer,:language,:text)"),
            [
                {"field": 1, "customer": 1, "language": language, "text": migration._OLD[language]},
                {"field": 1, "customer": 2, "language": language, "text": "customer override"},
                {"field": 2, "customer": 1, "language": language, "text": migration._OLD[language]},
            ],
        )
    before_overrides = _overrides(connection)

    migration.upgrade()
    migration.upgrade()
    assert _defaults(connection, migration._KEY) == tuple(
        "customer default" if language == custom_language else defaults[language]
        for language in ("sv", "en", "nb")
    )
    assert _defaults(connection, "other") == tuple(migration._OLD.values())
    assert _overrides(connection) == [
        (field, customer, language, defaults[language] if field == customer == 1 else text)
        for field, customer, language, text in before_overrides
    ]

    migration.downgrade()
    migration.downgrade()
    assert _defaults(connection, migration._KEY) == tuple(original.values())
    assert _defaults(connection, "other") == tuple(migration._OLD.values())
    assert _overrides(connection) == before_overrides
