"""The find_documents query guidance migration updates stored prompts and reverts."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = Path(__file__).parents[1] / "alembic/versions/187_find_documents_query_guidance.py"
    spec = importlib.util.spec_from_file_location("find_documents_query_guidance", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_find_documents_query_guidance_round_trip(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")
    seeds = {
        "workspace.chat.turn": (
            "Saknar du source_id för en dokumentmängd, anropa find_documents med "
            "användarens egna ord. En mening utan visningsanropet öppnar inget.",
            "If you lack source_id for a document set, call find_documents with the "
            "user's own words. A sentence without the display call opens nothing.",
        ),
        "workspace.voice.tool.find_documents": (
            "Hitta dokument-ID:n för en dokumenttyp via OverGraph. Använd mode=filter.",
            "Find document IDs for a document type via OverGraph. Use mode=filter.",
        ),
        "workspace.voice.task.document_find": (
            "För en dokumenttyp: hitta mängden med find_documents.",
            "For a document type, find the set with find_documents.",
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
        turn_sv, turn_en, turn_nb = rows["workspace.chat.turn"]
        assert "kompakt sökterm för dokumenttypen" in turn_sv
        assert "användarens egna ord" not in turn_sv
        assert turn_nb == turn_sv
        assert "compact search term for the document type" in turn_en
        assert "user's own words" not in turn_en
        tool_sv, _tool_en, _tool_nb = rows["workspace.voice.tool.find_documents"]
        assert tool_sv.count("Sätt query till en kompakt sökterm") == 1
        task_sv, _task_en, _task_nb = rows["workspace.voice.task.document_find"]
        assert task_sv.count("Skriv query som en kompakt sökterm") == 1

        migration.downgrade()

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
