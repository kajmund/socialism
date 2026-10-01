"""Database guards for immutable, backend-only shared chunk content."""

from sqlalchemy import DDL, Table, event

SQLITE_GUARD = """CREATE TRIGGER shared_text_chunks_immutable
BEFORE UPDATE ON shared_text_chunks BEGIN
SELECT RAISE(ABORT, 'shared chunk content is immutable'); END"""
PG_FUNCTION = """CREATE FUNCTION reject_shared_chunk_update() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'shared chunk content is immutable'; END; $$"""
PG_TRIGGER = """CREATE TRIGGER shared_text_chunks_immutable
BEFORE UPDATE ON shared_text_chunks FOR EACH ROW
EXECUTE FUNCTION reject_shared_chunk_update()"""
PG_REVOKE = """DO $$ DECLARE client_role text; BEGIN
FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
EXECUTE format('REVOKE ALL ON TABLE shared_text_chunks FROM %I', client_role);
END LOOP; END $$"""


def protect_shared_chunks(table: Table) -> None:
    event.listen(table, "after_create", DDL(SQLITE_GUARD).execute_if(dialect="sqlite"))
    for sql in (
        PG_FUNCTION, PG_TRIGGER,
        "ALTER TABLE shared_text_chunks ENABLE ROW LEVEL SECURITY", PG_REVOKE,
        "REVOKE EXECUTE ON FUNCTION reject_shared_chunk_update() FROM PUBLIC",
    ):
        event.listen(table, "after_create", DDL(sql.replace("%", "%%")).execute_if(dialect="postgresql"))
    event.listen(table, "after_drop", DDL(
        "DROP FUNCTION reject_shared_chunk_update()",
    ).execute_if(dialect="postgresql"))


def protect_text_unit_reference(table: Table) -> None:
    event.listen(table, "after_create", DDL("""CREATE TRIGGER text_unit_content_immutable
    BEFORE UPDATE OF content_hash ON text_units WHEN OLD.content_hash <> NEW.content_hash BEGIN
    SELECT RAISE(ABORT, 'TextUnit content reference is immutable'); END""").execute_if(dialect="sqlite"))
    event.listen(table, "after_create", DDL("""CREATE TRIGGER text_unit_content_immutable
    BEFORE UPDATE OF content_hash ON text_units FOR EACH ROW
    WHEN (OLD.content_hash IS DISTINCT FROM NEW.content_hash)
    EXECUTE FUNCTION reject_shared_chunk_update()""").execute_if(dialect="postgresql"))
