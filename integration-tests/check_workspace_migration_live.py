"""Exercise workspace migrations in the caller's empty, isolated PostgreSQL schema.

The caller supplies an admin AsyncConnection with a transaction and SET LOCAL
search_path already pointing at its disposable schema. No credentials, engine,
network calls or production-schema changes originate here. Every fixture and
migration change is rolled back to a savepoint before this function returns.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database.workspace_ids import company_workspace_id
from app.services.workspace_chat_prompts import workspace_prompt_fields

REPO = Path(__file__).resolve().parents[1]
WORKSPACE_TABLES = (
    "workspaces",
    "workspace_memberships",
    "workspace_chats",
    "workspace_chat_messages",
)


def _migration(connection, filename):
    spec = importlib.util.spec_from_file_location(
        filename.removesuffix(".py"), REPO / "backend/alembic/versions" / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    return module


def _fixture(connection) -> None:
    statements = (
        "CREATE TABLE kunder (id INTEGER PRIMARY KEY, name TEXT, organization_name TEXT)",
        "CREATE TABLE user_accounts (id VARCHAR(64) PRIMARY KEY)",
        "CREATE TABLE personas (id VARCHAR(64) PRIMARY KEY)",
        "CREATE TABLE jobs (id VARCHAR(64) PRIMARY KEY)",
        "CREATE TABLE stored_objects (id VARCHAR(64) PRIMARY KEY, customer_id INTEGER, kind TEXT)",
        "CREATE TABLE knowledge_questions (id VARCHAR(64) PRIMARY KEY, customer_id INTEGER, namespace TEXT)",
        "CREATE TABLE prompt_fields (id SERIAL PRIMARY KEY, key TEXT UNIQUE NOT NULL, modules JSON, section TEXT, label_sv TEXT, label_en TEXT, hint_sv TEXT, hint_en TEXT, default_sv TEXT, default_en TEXT, default_nb TEXT, active BOOLEAN)",
        "CREATE TABLE prompt_overrides (id SERIAL PRIMARY KEY, prompt_field_id INTEGER REFERENCES prompt_fields(id), text TEXT)",
        "INSERT INTO kunder VALUES (1,'Organisation A','Firm A'), (2,'Organisation B',NULL)",
        "INSERT INTO user_accounts VALUES ('user-a')",
        "INSERT INTO stored_objects VALUES ('a',1,'underlag'), ('b',2,'underlag'), ('report',1,'annual_report')",
        "INSERT INTO knowledge_questions VALUES ('q-a',1,'tenant:1'), ('q-b',2,'tenant:2'), ('q-public',NULL,'public')",
        "INSERT INTO prompt_fields (key,default_sv,active) VALUES ('existing.prompt','keep me',TRUE)",
        "INSERT INTO prompt_overrides (prompt_field_id,text) SELECT id,'keep override' FROM prompt_fields WHERE key='existing.prompt'",
    )
    for statement in statements:
        connection.execute(sa.text(statement))


def _check(results: list[dict], code: str, passed: bool, **details) -> None:
    results.append({"code": code, "passed": bool(passed), **details})
    if not passed:
        raise AssertionError(f"Workspace migration assertion failed: {code}")


def _rejected(connection, statement: str, parameters: dict, sqlstate: str) -> bool:
    try:
        with connection.begin_nested():
            connection.execute(sa.text(statement), parameters)
    except IntegrityError as exc:
        return getattr(exc.orig, "sqlstate", None) == sqlstate
    return False


def _verify_sources(connection, results: list[dict]) -> None:
    companies = dict(connection.execute(sa.text("SELECT customer_id,id FROM workspaces")).all())
    _check(results, "stable_company_ids", companies == {i: company_workspace_id(i) for i in (1, 2)})
    actual = connection.execute(
        sa.text("SELECT id,customer_id,kind,workspace_id FROM stored_objects ORDER BY id")
    ).all()
    _check(
        results,
        "underlag_assigned_and_artifact_unscoped",
        actual
        == [
            ("a", 1, "underlag", companies[1]),
            ("b", 2, "underlag", companies[2]),
            ("report", 1, "annual_report", None),
        ],
    )
    questions = dict(
        connection.execute(sa.text("SELECT id,namespace FROM knowledge_questions")).all()
    )
    _check(
        results,
        "private_questions_migrated_to_company",
        all(
            questions[f"q-{letter}"] == f"tenant:{i}:workspace:{companies[i]}"
            for i, letter in ((1, "a"), (2, "b"))
        ),
    )
    _check(results, "public_question_preserved", questions["q-public"] == "public")
    _check(
        results,
        "company_name_uses_organisation",
        connection.scalar(sa.text("SELECT name FROM workspaces WHERE customer_id=1")) == "Firm A",
    )


def _verify_constraints(connection, results: list[dict]) -> None:
    _check(
        results,
        "one_company_per_customer",
        _rejected(
            connection,
            "INSERT INTO workspaces (id,customer_id,name,kind) VALUES ('duplicate',1,'x','company')",
            {},
            "23505",
        ),
    )
    foreign = company_workspace_id(2)
    _check(
        results,
        "stored_object_cross_org_fk",
        _rejected(
            connection,
            "UPDATE stored_objects SET workspace_id=:workspace WHERE id='a'",
            {"workspace": foreign},
            "23503",
        ),
    )
    _check(
        results,
        "chat_cross_org_fk",
        _rejected(
            connection,
            "INSERT INTO workspace_chats (id,customer_id,workspace_id,owner_user_id,module,title) VALUES ('foreign-chat',1,:workspace,'user-a','dd','x')",
            {"workspace": foreign},
            "23503",
        ),
    )
    connection.execute(
        sa.text(
            "INSERT INTO workspace_chats (id,customer_id,workspace_id,owner_user_id,module,title) VALUES ('chat',1,:workspace,'user-a','dd','x')"
        ),
        {"workspace": company_workspace_id(1)},
    )
    ids = [
        connection.scalar(
            sa.text(
                "INSERT INTO workspace_chat_messages (chat_id,role,content) VALUES ('chat','user','hello') RETURNING id"
            )
        )
        for _ in range(2)
    ]
    _check(
        results,
        "chat_message_integer_sequence",
        all(isinstance(value, int) for value in ids) and ids[1] == ids[0] + 1,
    )


def _verify_security(connection, results: list[dict], roles: list[str]) -> None:
    for table in (*WORKSPACE_TABLES, "stored_objects"):
        values = connection.execute(
            sa.text(
                "SELECT relrowsecurity,(SELECT count(*) FROM pg_policy WHERE polrelid=c.oid) FROM pg_class c WHERE c.oid=to_regclass(:table)"
            ),
            {"table": table},
        ).one()
        _check(results, f"{table}_backend_rls", values == (True, 0))
        for role in roles:
            has_access = connection.scalar(
                sa.text(
                    "SELECT has_table_privilege(:role,to_regclass(:table),'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"
                ),
                {"role": role, "table": table},
            )
            _check(results, f"{table}_{role}_revoked", has_access is False)


def _verify_prompts(connection, results: list[dict], migration) -> None:
    keys = [field["key"] for field in workspace_prompt_fields()]
    migration.upgrade()
    actual = connection.execute(
        sa.text("SELECT key,active FROM prompt_fields WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": keys},
    ).all()
    _check(
        results,
        "workspace_prompt_fields_once",
        sorted(actual) == sorted((key, True) for key in keys),
    )
    _check(
        results,
        "existing_prompt_preserved",
        connection.scalar(
            sa.text("SELECT default_sv FROM prompt_fields WHERE key='existing.prompt'")
        )
        == "keep me",
    )
    connection.execute(
        sa.text(
            "INSERT INTO prompt_overrides (prompt_field_id,text) SELECT id,'workspace override' FROM prompt_fields WHERE key=:key"
        ),
        {"key": keys[0]},
    )


def _verify_downgrade(connection, results: list[dict]) -> None:
    tables = set(sa.inspect(connection).get_table_names())
    _check(results, "workspace_tables_removed", not tables.intersection(WORKSPACE_TABLES))
    columns = {column["name"] for column in sa.inspect(connection).get_columns("stored_objects")}
    _check(results, "workspace_column_removed", "workspace_id" not in columns)
    _check(
        results,
        "sources_preserved_after_downgrade",
        connection.execute(
            sa.text("SELECT id,customer_id,kind FROM stored_objects ORDER BY id")
        ).all()
        == [("a", 1, "underlag"), ("b", 2, "underlag"), ("report", 1, "annual_report")],
    )
    _check(
        results,
        "question_namespaces_restored",
        dict(connection.execute(sa.text("SELECT id,namespace FROM knowledge_questions")).all())
        == {"q-a": "tenant:1", "q-b": "tenant:2", "q-public": "public"},
    )
    _check(
        results,
        "workspace_prompt_fields_removed",
        connection.execute(sa.text("SELECT key FROM prompt_fields")).scalars().all()
        == ["existing.prompt"],
    )
    _check(
        results,
        "existing_prompt_override_preserved",
        connection.execute(sa.text("SELECT text FROM prompt_overrides")).scalars().all()
        == ["keep override"],
    )


def _validate(connection) -> list[dict]:
    if connection.dialect.name != "postgresql":
        raise ValueError("Migration live validation requires PostgreSQL")
    schema = connection.scalar(sa.text("SELECT current_schema()"))
    if schema in (None, "public", "auth", "storage", "extensions"):
        raise ValueError("Migration live validation requires an isolated schema")
    if sa.inspect(connection).get_table_names():
        raise ValueError("Migration live validation requires an empty schema")
    results = []
    savepoint = connection.begin_nested()
    try:
        _fixture(connection)
        roles = (
            connection.execute(
                sa.text(
                    "SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') ORDER BY rolname"
                )
            )
            .scalars()
            .all()
        )
        quoted_schema = connection.dialect.identifier_preparer.quote(schema)
        for role in roles:
            quoted_role = connection.dialect.identifier_preparer.quote(role)
            connection.execute(
                sa.text(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {quoted_schema} GRANT ALL ON TABLES TO {quoted_role}"
                )
            )
            connection.execute(sa.text(f"GRANT ALL ON TABLE stored_objects TO {quoted_role}"))
        workspaces = _migration(connection, "149_workspaces.py")
        prompts = _migration(connection, "150_workspace_chat_prompts.py")
        workspaces.upgrade()
        prompts.upgrade()
        _verify_sources(connection, results)
        _verify_constraints(connection, results)
        _verify_security(connection, results, roles)
        _verify_prompts(connection, results, prompts)
        prompts.downgrade()
        workspaces.downgrade()
        _verify_downgrade(connection, results)
    finally:
        savepoint.rollback()
    _check(results, "fixtures_rolled_back", not sa.inspect(connection).get_table_names())
    return results


async def validate(connection: AsyncConnection) -> list[dict]:
    """Return named assertions; raise on failure and leave the schema empty."""
    return await connection.run_sync(_validate)
