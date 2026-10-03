"""Migration149 supports isolated upgrades/downgrades and closed Postgres roles."""

from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.database.base import Base

TABLES = {
    "workspace_chats", "workspace_sources", "workspace_expert_threads", "workspace_research",
    "workspace_references", "workspace_artifacts", "workspace_artifact_revisions", "workspace_operations",
    "workspace_conversation_sessions", "workspace_conversation_events", "workspace_agent_deployments",
}


def config() -> Config:
    return Config(str(Path(__file__).parents[1] / "alembic.ini"))


def test_sqlite_workspace_upgrade_from_148_and_downgrade(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path}/workspace-migration.db"
    monkeypatch.setenv("MIGRATION_DATABASE_URL", database_url)
    command.upgrade(config(), "148_expert_async_tool_prompts")
    engine = create_engine(database_url)
    before = set(inspect(engine).get_table_names())
    assert not before.intersection(TABLES)
    command.upgrade(config(), "149_live_voice_workspaces")
    inspector = inspect(engine)
    assert TABLES <= set(inspector.get_table_names())
    for name in TABLES:
        migrated = {column["name"] for column in inspector.get_columns(name)}
        assert migrated == set(Base.metadata.tables[name].columns.keys())
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO kunder(id,name,slug,available_modules) VALUES(42,'QA','qa','[]')"))
        connection.execute(text("INSERT INTO user_accounts(id,email,role,kund_id) VALUES('qa-user','qa@example.test','user',42)"))
        connection.execute(text("INSERT INTO workspace_chats(id,customer_id,owner_user_id,title,module,state,creation_key,creation_payload_hash) VALUES('qa-ws',42,'qa-user','QA','dd','{}','creation','hash')"))
        assert connection.execute(text("SELECT revision,next_reference_number FROM workspace_chats")).one() == (0, 1)
    command.downgrade(config(), "148_expert_async_tool_prompts")
    assert set(inspect(engine).get_table_names()) == before
    command.upgrade(config(), "149_live_voice_workspaces")
    assert TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_postgres_offline_sql_enables_rls_and_revokes_client_roles(monkeypatch):
    # Offline SQL generation cannot open a database connection.
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql+psycopg://qa:unused@127.0.0.1/workspace_qa")
    output = StringIO()
    migration_config = config()
    migration_config.output_buffer = output
    command.upgrade(migration_config, "148_expert_async_tool_prompts:149_live_voice_workspaces", sql=True)
    sql = output.getvalue()
    for table in TABLES:
        assert f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY' in sql
        for role in ("PUBLIC", '"anon"', '"authenticated"'):
            assert f'REVOKE ALL ON TABLE public."{table}" FROM {role}' in sql
    assert "uq_workspace_creation_key" in sql
