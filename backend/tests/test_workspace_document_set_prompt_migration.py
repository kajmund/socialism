"""The document-set tool is seeded and existing workspace prompts are upgraded."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa


def test_document_set_prompt_migration_round_trip(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/178_workspace_document_sets.py"
    spec = importlib.util.spec_from_file_location("workspace_document_set_prompt_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE prompt_fields (id INTEGER PRIMARY KEY, key TEXT UNIQUE, modules JSON, section TEXT, "
            "label_sv TEXT, label_en TEXT, hint_sv TEXT, hint_en TEXT, default_sv TEXT, default_en TEXT, "
            "default_nb TEXT, active BOOLEAN)"
        ))
        connection.execute(sa.text(
            "CREATE TABLE prompt_overrides (prompt_field_id INTEGER, customer_id INTEGER, language TEXT, text TEXT)"
        ))
        for identifier, (key, old_sv, _new_sv, old_en, _new_en) in enumerate(migration._REPLACEMENTS, start=1):
            connection.execute(
                sa.text(
                    "INSERT INTO prompt_fields "
                    "(id,key,default_sv,default_en,default_nb) VALUES (:id,:key,:sv,:en,:nb)"
                ),
                {"id": identifier, "key": key, "sv": old_sv, "en": old_en, "nb": old_sv},
            )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        migration.upgrade()

        assert connection.scalar(sa.text(
            "SELECT COUNT(*) FROM prompt_fields WHERE key=:key"
        ), {"key": migration._KEY}) == 1
        for key, _old_sv, new_sv, _old_en, new_en in migration._REPLACEMENTS:
            row = connection.execute(
                sa.text("SELECT default_sv,default_en,default_nb FROM prompt_fields WHERE key=:key"),
                {"key": key},
            ).one()
            assert tuple(row) == (new_sv, new_en, new_sv)

        migration.downgrade()

        assert connection.scalar(sa.text(
            "SELECT COUNT(*) FROM prompt_fields WHERE key=:key"
        ), {"key": migration._KEY}) == 0
        for key, old_sv, _new_sv, old_en, _new_en in migration._REPLACEMENTS:
            row = connection.execute(
                sa.text("SELECT default_sv,default_en,default_nb FROM prompt_fields WHERE key=:key"),
                {"key": key},
            ).one()
            assert tuple(row) == (old_sv, old_en, old_sv)
    engine.dispose()
