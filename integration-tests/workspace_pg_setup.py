"""Expose real pgvector in an isolated schema without exposing public tables."""

from sqlalchemy import inspect, text


async def install_vector_aliases(connection, schema: str) -> dict:
    vector = (
        (
            await connection.execute(
                text("""
        SELECT n.nspname AS type_schema, pn.nspname AS function_schema, p.proname
        FROM pg_extension e
        JOIN pg_namespace n ON n.oid=e.extnamespace
        JOIN pg_type t ON t.typnamespace=n.oid AND t.typname='vector'
        JOIN pg_operator o ON o.oprnamespace=n.oid AND o.oprleft=t.oid AND o.oprright=t.oid AND o.oprname='<=>'
        JOIN pg_proc p ON p.oid=o.oprcode
        JOIN pg_namespace pn ON pn.oid=p.pronamespace
        WHERE e.extname='vector'
    """)
            )
        )
        .mappings()
        .one()
    )
    quote = connection.dialect.identifier_preparer.quote
    target = quote(schema)
    base = f"{quote(vector['type_schema'])}.vector"
    procedure = f"{quote(vector['function_schema'])}.{quote(vector['proname'])}"
    await connection.execute(text(f"CREATE DOMAIN {target}.vector AS {base}"))
    await connection.execute(
        text(
            f"CREATE OPERATOR {target}.<=> (LEFTARG={base}, RIGHTARG={base}, PROCEDURE={procedure})"
        )
    )
    distance = await connection.scalar(
        text("SELECT CAST('[1,0,0]' AS vector) <=> CAST('[1,0,0]' AS vector)")
    )
    if distance != 0:
        raise RuntimeError("Isolated pgvector alias did not use cosine distance")
    return {"vector_extension_namespace": vector["type_schema"], "vector_alias_verified": True}


async def initialize_isolated_schema(admin_engine, *, schema: str, app_role: str, metadata) -> dict:
    from check_workspace_migration_live import validate

    if any(table.schema is not None for table in metadata.tables.values()):
        raise RuntimeError("Fixture metadata must not target an external schema")
    async with admin_engine.begin() as connection:
        quote = connection.dialect.identifier_preparer.quote
        await connection.execute(text(f"SET LOCAL search_path TO {quote(schema)}"))
        if await connection.scalar(text("SELECT current_schema()")) != schema:
            raise RuntimeError("Migration connection schema isolation failed")
        checks = await validate(connection)
        report = await install_vector_aliases(connection, schema)
        await connection.run_sync(lambda sync: metadata.create_all(sync, checkfirst=False))
        tables = await connection.run_sync(
            lambda sync: inspect(sync).get_table_names(schema=schema)
        )
        expected = {table.name for table in metadata.tables.values()}
        if set(tables) != expected:
            raise RuntimeError("Fixture tables were not all created in the isolated schema")
        role = quote(app_role)
        await connection.execute(text(f"GRANT USAGE ON SCHEMA {quote(schema)} TO {role}"))
        await connection.execute(text(f"GRANT USAGE ON TYPE {quote(schema)}.vector TO {role}"))
        await connection.execute(
            text(f"GRANT ALL ON ALL TABLES IN SCHEMA {quote(schema)} TO {role}")
        )
        await connection.execute(
            text(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA {quote(schema)} TO {role}")
        )
        role_flags = (
            await connection.execute(
                text("SELECT rolbypassrls,rolsuper FROM pg_roles WHERE rolname=:role"),
                {"role": app_role},
            )
        ).one()
    return {
        **report,
        "migration_checks": checks,
        "isolated_base_tables": len(expected),
        "base_table_schema_verified": True,
        "app_role_bypass_rls": role_flags[0],
        "app_role_superuser": role_flags[1],
    }
