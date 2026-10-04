"""Existing private underlag receives a durable company scope at migration time."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def workspace_migration(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/149_workspaces.py"
    spec = importlib.util.spec_from_file_location("workspace_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql(
            "CREATE TABLE kunder (id INTEGER PRIMARY KEY, name TEXT, organization_name TEXT)"
        )
        connection.exec_driver_sql("CREATE TABLE user_accounts (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE personas (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE jobs (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE knowledge_questions (id TEXT PRIMARY KEY, customer_id INTEGER, namespace TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO knowledge_questions VALUES ('q', 1, 'tenant:1'), ('public', NULL, 'public')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE stored_objects (id TEXT PRIMARY KEY, customer_id INTEGER, kind TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO kunder VALUES (1, 'Organisation A', 'Firm A'), (2, 'Organisation B', NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO stored_objects VALUES ('a', 1, 'underlag'), ('b', 2, 'underlag'), ('report', 1, 'annual_report')"
        )
        connection.commit()
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        connection.commit()
        yield module, connection
    engine.dispose()


def test_existing_underlag_is_assigned_to_its_company_and_roundtrip_preserves_objects(
    workspace_migration,
):
    migration, connection = workspace_migration
    rows = (
        connection.execute(
            sa.text("SELECT id, customer_id, kind, workspace_id FROM stored_objects ORDER BY id")
        )
        .mappings()
        .all()
    )
    companies = dict(connection.execute(sa.text("SELECT customer_id, id FROM workspaces")).all())
    assert len(companies) == 2
    assert (
        connection.scalar(sa.text("SELECT namespace FROM knowledge_questions WHERE id = 'q'"))
        == f"tenant:1:workspace:{companies[1]}"
    )
    assert (
        connection.scalar(sa.text("SELECT namespace FROM knowledge_questions WHERE id = 'public'"))
        == "public"
    )
    assert rows[0]["workspace_id"] == companies[1]
    assert rows[1]["workspace_id"] == companies[2]
    assert rows[2]["workspace_id"] is None
    assert (
        connection.scalar(sa.text("SELECT name FROM workspaces WHERE customer_id = 1")) == "Firm A"
    )
    migration.downgrade()
    assert (
        connection.scalar(sa.text("SELECT namespace FROM knowledge_questions WHERE id = 'q'"))
        == "tenant:1"
    )
    assert "workspaces" not in sa.inspect(connection).get_table_names()
    assert connection.scalar(sa.text("SELECT count(*) FROM stored_objects")) == 3
    assert "workspace_id" not in {
        column["name"] for column in sa.inspect(connection).get_columns("stored_objects")
    }


def test_database_rejects_second_company_and_cross_organisation_chat(workspace_migration):
    _migration, connection = workspace_migration
    with pytest.raises(IntegrityError):
        connection.execute(
            sa.text(
                "INSERT INTO workspaces (id,customer_id,name,kind) VALUES ('duplicate',1,'x','company')"
            )
        )
    connection.execute(sa.text("INSERT INTO user_accounts VALUES ('user-a')"))
    foreign = connection.scalar(sa.text("SELECT id FROM workspaces WHERE customer_id = 2"))
    with pytest.raises(IntegrityError):
        connection.execute(
            sa.text("UPDATE stored_objects SET workspace_id = :workspace WHERE id = 'a'"),
            {"workspace": foreign},
        )
    with pytest.raises(IntegrityError):
        connection.execute(
            sa.text(
                "INSERT INTO workspace_chats (id,customer_id,workspace_id,owner_user_id,module,title) VALUES ('chat',1,:workspace,'user-a','expertgranskning','x')"
            ),
            {"workspace": foreign},
        )


def test_new_workspace_tables_are_secured_for_postgres(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/149_workspaces.py"
    spec = importlib.util.spec_from_file_location("workspace_migration_security", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    engine = sa.create_mock_engine("postgresql://", lambda *_args: None)
    module._secure_backend_tables(engine)
    for table in (
        "workspaces",
        "workspace_memberships",
        "workspace_chats",
        "workspace_chat_messages",
        "stored_objects",
    ):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in statements
        revokes = [
            statement for statement in statements if f"REVOKE ALL ON TABLE {table}" in statement
        ]
        assert len(revokes) == 1
        assert "'anon', 'authenticated'" in revokes[0]
