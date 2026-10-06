"""The voice agent receives the open contract text and can name a party from it."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.services.workspace_document_context import (
    build_excerpts,
    matching_source_id,
    open_request_terms,
    select_excerpt_ids,
)


def test_one_ready_document_is_included_when_nothing_is_open():
    inventory = [{"source_object_id": "contract", "filename": "avtal.pdf", "knowledge_status": "ready"}]
    assert select_excerpt_ids(inventory, []) == ["contract"]


def test_several_files_stay_out_of_the_turn_until_one_is_open():
    inventory = [
        {"source_object_id": "a", "filename": "a.pdf", "knowledge_status": "ready"},
        {"source_object_id": "b", "filename": "b.pdf", "knowledge_status": "ready"},
    ]
    assert select_excerpt_ids(inventory, []) == []
    assert select_excerpt_ids(inventory, ["b"]) == ["b"]


def test_open_request_matches_the_customer_inside_the_contract():
    inventory = [
        {"source_object_id": "contract", "filename": "Avtal_-_Konsulttja_nster.pdf", "knowledge_status": "ready"},
        {"source_object_id": "news", "filename": "a3p-nyhetsbrev.pdf", "knowledge_status": "ready"},
    ]
    texts = {
        "contract": "Kund: A. Ateles Consulting AB",
        "news": "Aktieägarnyhetsbrev från A3P",
    }
    terms = open_request_terms("öppna avtalet med ateles som kund", [])
    assert terms == ["ateles"]
    assert matching_source_id(inventory, texts, terms, "") == "contract"
    assert open_request_terms("öppna det", ["öppna avtalet med ateles som kund"]) == ["ateles"]
    assert matching_source_id(inventory, texts, ["ateles", "nyhetsbrev"], "") is None


def test_excerpt_keeps_the_opening_pages_and_marks_the_rest():
    inventory = {"contract": {"filename": "avtal.pdf", "knowledge_status": "ready"}}
    excerpts = build_excerpts(["contract"], inventory, {"contract": "Kund: Aurora AB. " + ("x" * 50)}, limit=20)
    assert excerpts[0]["text"].startswith("Kund: Aurora AB.")
    assert excerpts[0]["truncated"] is True
    assert len(excerpts[0]["text"]) == 20


@pytest.fixture
def answer_prompt_migration(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/155_workspace_document_answer.py"
    spec = importlib.util.spec_from_file_location("workspace_document_answer_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE prompt_fields (id INTEGER PRIMARY KEY, key TEXT UNIQUE, "
            "default_sv TEXT, default_en TEXT, default_nb TEXT)"
        ))
        connection.execute(sa.text(
            "CREATE TABLE prompt_overrides (prompt_field_id INTEGER, customer_id INTEGER, language TEXT, text TEXT)"
        ))
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        yield migration, connection
    engine.dispose()


def test_document_answer_upgrade_inserts_the_paragraph_and_preserves_custom_text(answer_prompt_migration):
    migration, connection = answer_prompt_migration
    system = migration._catalog(migration._SYSTEM)
    previous = {language: migration._previous_system(language) for language in ("sv", "en", "nb")}
    connection.execute(sa.text(
        "INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) VALUES (1,:key,:sv,:en,:nb)"
    ), {"key": migration._SYSTEM, **previous})
    connection.execute(sa.text(
        "INSERT INTO prompt_overrides VALUES (1,1,'sv',:text)"
    ), {"text": previous["sv"]})
    connection.execute(sa.text(
        "INSERT INTO prompt_overrides VALUES (1,2,'sv','egen text')"
    ))
    migration.upgrade()
    migration.upgrade()
    row = connection.execute(sa.text("SELECT default_sv,default_en,default_nb FROM prompt_fields")).one()
    assert tuple(row) == tuple(system[language] for language in ("sv", "en", "nb"))
    overrides = connection.execute(sa.text("SELECT customer_id,text FROM prompt_overrides ORDER BY customer_id")).all()
    assert overrides == [(1, system["sv"]), (2, "egen text")]
    migration.downgrade()
    restored = connection.execute(sa.text("SELECT default_sv FROM prompt_fields")).scalar_one()
    assert restored == previous["sv"]
    assert "open_documents i kontexten" not in restored


@pytest.fixture
def focus_prompt_migration(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/156_workspace_focus_passage.py"
    spec = importlib.util.spec_from_file_location("workspace_focus_passage_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE prompt_fields (id INTEGER PRIMARY KEY, key TEXT UNIQUE, "
            "default_sv TEXT, default_en TEXT, default_nb TEXT)"
        ))
        connection.execute(sa.text(
            "CREATE TABLE prompt_overrides (prompt_field_id INTEGER, customer_id INTEGER, language TEXT, text TEXT)"
        ))
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        yield migration, connection
    engine.dispose()


def test_focus_passage_upgrade_inserts_the_paragraph_and_preserves_custom_text(focus_prompt_migration):
    migration, connection = focus_prompt_migration
    system = migration._catalog(migration._SYSTEM)
    tool = migration._catalog(migration._TOOL)
    previous = {language: migration._previous_system(language) for language in ("sv", "en", "nb")}
    connection.execute(sa.text(
        "INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) VALUES (1,:key,:sv,:en,:nb)"
    ), {"key": migration._SYSTEM, **previous})
    connection.execute(sa.text(
        "INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) VALUES (2,:key,:sv,:en,:nb)"
    ), {"key": migration._TOOL, **migration._TOOL_OLD})
    connection.execute(sa.text("INSERT INTO prompt_overrides VALUES (1,1,'sv',:text)"), {"text": previous["sv"]})
    connection.execute(sa.text("INSERT INTO prompt_overrides VALUES (1,2,'sv','egen text')"))
    migration.upgrade()
    migration.upgrade()
    row = connection.execute(sa.text(
        "SELECT default_sv,default_en,default_nb FROM prompt_fields WHERE key = :key"
    ), {"key": migration._SYSTEM}).one()
    assert tuple(row) == tuple(system[language] for language in ("sv", "en", "nb"))
    tool_row = connection.execute(sa.text("SELECT default_sv FROM prompt_fields WHERE key = :key"),
                                  {"key": migration._TOOL}).scalar_one()
    assert tool_row == tool["sv"]
    overrides = connection.execute(sa.text(
        "SELECT customer_id,text FROM prompt_overrides ORDER BY customer_id")).all()
    assert overrides == [(1, system["sv"]), (2, "egen text")]
    migration.downgrade()
    restored = connection.execute(sa.text(
        "SELECT default_sv FROM prompt_fields WHERE key = :key"), {"key": migration._SYSTEM}).scalar_one()
    assert restored == previous["sv"]
    assert "Säg aldrig att du inte kan markera" not in restored


@pytest.fixture
def open_prompt_migration(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/157_workspace_open_document.py"
    spec = importlib.util.spec_from_file_location("workspace_open_document_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE prompt_fields (id INTEGER PRIMARY KEY, key TEXT UNIQUE, "
            "default_sv TEXT, default_en TEXT, default_nb TEXT)"
        ))
        connection.execute(sa.text(
            "CREATE TABLE prompt_overrides (prompt_field_id INTEGER, customer_id INTEGER, language TEXT, text TEXT)"
        ))
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        yield migration, connection
    engine.dispose()


def test_open_document_upgrade_inserts_the_paragraph_and_preserves_custom_text(open_prompt_migration):
    migration, connection = open_prompt_migration
    system = migration._catalog(migration._SYSTEM)
    tool = migration._catalog(migration._TOOL)
    previous = {language: migration._previous_system(language) for language in ("sv", "en", "nb")}
    connection.execute(sa.text(
        "INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) VALUES (1,:key,:sv,:en,:nb)"
    ), {"key": migration._SYSTEM, **previous})
    connection.execute(sa.text(
        "INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) VALUES (2,:key,:sv,:en,:nb)"
    ), {"key": migration._TOOL, **migration._TOOL_OLD})
    connection.execute(sa.text("INSERT INTO prompt_overrides VALUES (1,1,'sv',:text)"), {"text": previous["sv"]})
    connection.execute(sa.text("INSERT INTO prompt_overrides VALUES (1,2,'sv','egen text')"))
    migration.upgrade()
    migration.upgrade()
    row = connection.execute(sa.text(
        "SELECT default_sv,default_en,default_nb FROM prompt_fields WHERE key = :key"
    ), {"key": migration._SYSTEM}).one()
    assert tuple(row) == tuple(system[language] for language in ("sv", "en", "nb"))
    tool_row = connection.execute(sa.text("SELECT default_sv FROM prompt_fields WHERE key = :key"),
                                  {"key": migration._TOOL}).scalar_one()
    assert tool_row == tool["sv"]
    overrides = connection.execute(sa.text(
        "SELECT customer_id,text FROM prompt_overrides ORDER BY customer_id")).all()
    assert overrides == [(1, system["sv"]), (2, "egen text")]
    migration.downgrade()
    restored = connection.execute(sa.text(
        "SELECT default_sv FROM prompt_fields WHERE key = :key"), {"key": migration._SYSTEM}).scalar_one()
    assert restored == previous["sv"]
    assert "Fråga inte om du ska öppna det" not in restored


@pytest.fixture
def search_prompt_migration(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/158_workspace_search_documents.py"
    spec = importlib.util.spec_from_file_location("workspace_search_documents_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE prompt_fields (id INTEGER PRIMARY KEY, key TEXT UNIQUE, "
            "default_sv TEXT, default_en TEXT, default_nb TEXT)"
        ))
        connection.execute(sa.text(
            "CREATE TABLE prompt_overrides (prompt_field_id INTEGER, customer_id INTEGER, language TEXT, text TEXT)"
        ))
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        yield migration, connection
    engine.dispose()


def test_document_search_upgrade_replaces_the_filename_question(search_prompt_migration):
    migration, connection = search_prompt_migration
    system = migration._catalog(migration._SYSTEM)
    previous = {language: migration._previous_system(language) for language in ("sv", "en", "nb")}
    connection.execute(sa.text(
        "INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) VALUES (1,:key,:sv,:en,:nb)"
    ), {"key": migration._SYSTEM, **previous})
    for index, key in enumerate(migration._TOOLS, start=2):
        old = migration._TOOLS[key]
        connection.execute(sa.text(
            "INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) VALUES (:id,:key,:sv,:en,:nb)"
        ), {"id": index, "key": key, **old})
    connection.execute(sa.text("INSERT INTO prompt_overrides VALUES (1,1,'sv',:text)"), {"text": previous["sv"]})
    connection.execute(sa.text("INSERT INTO prompt_overrides VALUES (1,2,'sv','egen text')"))
    migration.upgrade()
    migration.upgrade()
    row = connection.execute(sa.text(
        "SELECT default_sv,default_en,default_nb FROM prompt_fields WHERE key = :key"
    ), {"key": migration._SYSTEM}).one()
    assert tuple(row) == tuple(system[language] for language in ("sv", "en", "nb"))
    assert "anropa search_knowledge med de orden" in row[0]
    search_tool = connection.execute(sa.text("SELECT default_sv FROM prompt_fields WHERE key = :key"),
                                     {"key": "workspace.voice.tool.search_knowledge"}).scalar_one()
    assert search_tool == migration._catalog("workspace.voice.tool.search_knowledge")["sv"]
    overrides = connection.execute(sa.text(
        "SELECT customer_id,text FROM prompt_overrides ORDER BY customer_id")).all()
    assert overrides == [(1, system["sv"]), (2, "egen text")]
    migration.downgrade()
    restored = connection.execute(sa.text(
        "SELECT default_sv FROM prompt_fields WHERE key = :key"), {"key": migration._SYSTEM}).scalar_one()
    assert restored == previous["sv"]
    assert "anropa search_knowledge med de orden" not in restored
