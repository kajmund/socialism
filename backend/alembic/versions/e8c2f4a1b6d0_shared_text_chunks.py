"""Store exact chunk text once; TextUnits remain scoped provenance occurrences."""

import hashlib

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from alembic import op

revision = "e8c2f4a1b6d0"
down_revision = "141_canonical_evidence_nature"
branch_labels = None
depends_on = None

UNITS = sa.table("text_units", sa.column("id"), sa.column("content_hash"), sa.column("text"))
CHUNKS = sa.table("shared_text_chunks", sa.column("content_hash"), sa.column("text"))


def _lock(connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("LOCK TABLE text_units IN ACCESS EXCLUSIVE MODE")
    else:
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar():
            raise RuntimeError("SQLite batch migration requires foreign_keys=OFF before transaction")
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")


def _batches(connection):
    result = connection.execute(sa.select(UNITS).order_by(UNITS.c.id)).mappings()
    while rows := result.fetchmany(200):
        yield rows


def _validate(connection) -> None:
    for batch in _batches(connection):
        for row in batch:
            if hashlib.sha256(row["text"].encode("utf-8")).hexdigest() != row["content_hash"]:
                raise ValueError(f"TextUnit {row['id']} SHA does not match its exact text")


def _guards(connection) -> None:
    if connection.dialect.name == "sqlite":
        op.execute("""CREATE TRIGGER shared_text_chunks_immutable
        BEFORE UPDATE ON shared_text_chunks BEGIN
        SELECT RAISE(ABORT, 'shared chunk content is immutable'); END""")
        op.execute("""CREATE TRIGGER text_unit_content_immutable
        BEFORE UPDATE OF content_hash ON text_units WHEN OLD.content_hash <> NEW.content_hash BEGIN
        SELECT RAISE(ABORT, 'TextUnit content reference is immutable'); END""")
        return
    op.execute("""CREATE FUNCTION reject_shared_chunk_update() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'shared chunk content is immutable'; END; $$""")
    op.execute("""CREATE TRIGGER shared_text_chunks_immutable
    BEFORE UPDATE ON shared_text_chunks FOR EACH ROW
    EXECUTE FUNCTION reject_shared_chunk_update()""")
    op.execute("""CREATE TRIGGER text_unit_content_immutable
    BEFORE UPDATE OF content_hash ON text_units FOR EACH ROW
    WHEN (OLD.content_hash IS DISTINCT FROM NEW.content_hash)
    EXECUTE FUNCTION reject_shared_chunk_update()""")
    op.execute("ALTER TABLE shared_text_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("""DO $$ DECLARE client_role text; BEGIN
    FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
    EXECUTE format('REVOKE ALL ON TABLE shared_text_chunks FROM %I', client_role);
    END LOOP; END $$""")
    op.execute("REVOKE EXECUTE ON FUNCTION reject_shared_chunk_update() FROM PUBLIC")


def upgrade() -> None:
    connection = op.get_bind()
    _lock(connection)
    _validate(connection)
    op.create_table("shared_text_chunks",
        sa.Column("content_hash", sa.String(64), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
    )
    insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}[connection.dialect.name]
    for batch in _batches(connection):
        contents = {row["content_hash"]: row["text"] for row in batch}
        connection.execute(insert(CHUNKS).values([
            {"content_hash": key, "text": text} for key, text in contents.items()
        ]).on_conflict_do_nothing(index_elements=["content_hash"]))
    with op.batch_alter_table("text_units") as batch:
        batch.drop_column("text")
        batch.create_foreign_key("fk_text_units_shared_content", "shared_text_chunks",
            ["content_hash"], ["content_hash"], ondelete="RESTRICT",
        )
    _guards(connection)


def downgrade() -> None:
    connection = op.get_bind()
    _lock(connection)
    op.execute("DROP TRIGGER text_unit_content_immutable" + (
        " ON text_units" if connection.dialect.name == "postgresql" else ""
    ))
    op.add_column("text_units", sa.Column("text", sa.Text(), nullable=True))
    connection.execute(sa.text("""UPDATE text_units SET text = (
        SELECT text FROM shared_text_chunks WHERE content_hash = text_units.content_hash
    )"""))
    with op.batch_alter_table("text_units") as batch:
        batch.drop_constraint("fk_text_units_shared_content", type_="foreignkey")
        batch.alter_column("text", existing_type=sa.Text(), nullable=False)
    op.drop_table("shared_text_chunks")
    if connection.dialect.name == "postgresql":
        op.execute("DROP FUNCTION reject_shared_chunk_update()")
