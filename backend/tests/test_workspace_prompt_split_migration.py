"""Prompt split migration preserves exact overrides and round-trips defaults."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa


def _load_migration():
    path = Path(__file__).parents[1] / "alembic/versions/180_workspace_prompt_split.py"
    spec = importlib.util.spec_from_file_location("workspace_prompt_split_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_workspace_prompt_split_migration_round_trip(monkeypatch):
    migration = _load_migration()
    old = migration._texts(legacy=True)
    new = migration._texts(legacy=False)
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
        for identifier, key in enumerate(migration._UPDATED_KEYS, start=1):
            row = old[key]
            connection.execute(
                sa.text(
                    "INSERT INTO prompt_fields "
                    "(id,key,default_sv,default_en,default_nb) "
                    "VALUES (:id,:key,:sv,:en,:nb)"
                ),
                {
                    "id": identifier,
                    "key": key,
                    "sv": row["sv"],
                    "en": row["en"],
                    "nb": row["sv"],
                },
            )
        system_id = 1
        connection.execute(
            sa.text(
                "INSERT INTO prompt_overrides "
                "(prompt_field_id,customer_id,language,text) "
                "VALUES (:id,1,'sv',:text),(:id,2,'sv','kundanpassad')"
            ),
            {"id": system_id, "text": old["workspace.voice.system"]["sv"]},
        )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        migration.upgrade()

        for key in migration._UPDATED_KEYS:
            row = connection.execute(
                sa.text(
                    "SELECT default_sv,default_en,default_nb "
                    "FROM prompt_fields WHERE key=:key"
                ),
                {"key": key},
            ).one()
            assert tuple(row) == (new[key]["sv"], new[key]["en"], new[key]["sv"])
        assert connection.scalar(sa.text(
            "SELECT COUNT(*) FROM prompt_fields WHERE key LIKE 'workspace.voice.task.%'"
        )) == 3
        overrides = connection.execute(
            sa.text(
                "SELECT customer_id,text FROM prompt_overrides "
                "WHERE prompt_field_id=:id ORDER BY customer_id"
            ),
            {"id": system_id},
        ).all()
        assert overrides == [
            (1, new["workspace.voice.system"]["sv"]),
            (2, "kundanpassad"),
        ]

        migration.downgrade()

        assert connection.scalar(sa.text(
            "SELECT COUNT(*) FROM prompt_fields WHERE key LIKE 'workspace.voice.task.%'"
        )) == 0
        system = connection.execute(
            sa.text(
                "SELECT default_sv,default_en,default_nb "
                "FROM prompt_fields WHERE key='workspace.voice.system'"
            )
        ).one()
        assert tuple(system) == (
            old["workspace.voice.system"]["sv"],
            old["workspace.voice.system"]["en"],
            old["workspace.voice.system"]["sv"],
        )
    engine.dispose()
