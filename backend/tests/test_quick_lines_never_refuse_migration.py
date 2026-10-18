"""Migration 189 forbids refusals in the quick chat lines and reverts."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = Path(__file__).parents[1] / "alembic/versions/189_quick_lines_never_refuse.py"
    spec = importlib.util.spec_from_file_location("quick_lines_never_refuse", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_quick_lines_never_refuse_round_trip(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")
    seeds = {
        "chat.expert.quick_draft": (
            "Det här är en kort kvittensrad, inte ett svar. Ingen upprepning av frågan.",
            "This is a short acknowledgment line, not an answer. No restating the question.",
        ),
        "chat.expert.quick_progress": (
            "Det fullständiga svaret dröjer fortfarande. Svara inte på frågan.",
            "The full reply is still late. Do not answer the question.",
        ),
    }
    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE prompt_fields (id INTEGER PRIMARY KEY, key TEXT UNIQUE, "
            "default_sv TEXT, default_en TEXT, default_nb TEXT)"
        ))
        for identifier, (key, (sv, en)) in enumerate(seeds.items(), start=1):
            connection.execute(
                sa.text(
                    "INSERT INTO prompt_fields (id,key,default_sv,default_en,default_nb) "
                    "VALUES (:id,:key,:sv,:en,:nb)"
                ),
                {"id": identifier, "key": key, "sv": sv, "en": en, "nb": sv},
            )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        migration.upgrade()
        migration.upgrade()  # idempotent: no duplicated sentences

        rows = {
            row[0]: (row[1], row[2], row[3])
            for row in connection.execute(
                sa.text("SELECT key, default_sv, default_en, default_nb FROM prompt_fields")
            )
        }
        draft_sv, draft_en, draft_nb = rows["chat.expert.quick_draft"]
        assert draft_sv.count("Säg aldrig att du inte kan hjälpa") == 1
        assert draft_nb == draft_sv
        assert draft_en.count("Never say you cannot help") == 1
        progress_sv, progress_en, progress_nb = rows["chat.expert.quick_progress"]
        assert progress_sv.count("Säg aldrig att du inte kan hjälpa") == 1
        assert progress_nb == progress_sv
        assert progress_en.count("Never say you cannot help") == 1

        migration.downgrade()
        migration.downgrade()  # idempotent: nothing left to remove

        rows = {
            row[0]: (row[1], row[2], row[3])
            for row in connection.execute(
                sa.text("SELECT key, default_sv, default_en, default_nb FROM prompt_fields")
            )
        }
        for key, (old_sv, old_en) in seeds.items():
            got_sv, got_en, got_nb = rows[key]
            assert got_sv == old_sv, key
            assert got_en == old_en, key
            assert got_nb == old_sv, key
    engine.dispose()
