"""Replay TextUnit rows preserved by migration 191 into OverGraph, with verification.

python -m app.services.knowledge.backfill_text_units
python -m app.services.knowledge.backfill_text_units --drop-backup

Migration ``191_drop_text_units`` copies any rows left in the retired SQL mirror to
``text_units_dropped`` / ``shared_text_chunks_dropped`` so an upgrade never blocks.
This command replays them into OverGraph and then **proves** the replay:

1. every backup row's ``content_hash`` must equal ``sha256`` of its stored text,
2. every row is upserted into the knowledge catalog,
3. every row is read back from OverGraph and compared field by field.

``--drop-backup`` is refused unless every row passed all three checks, so the only
way to remove the backup is on verified, non-lossy data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from app.config import settings
from app.database.session import engine
from app.services.knowledge.scope import customer_scope, shared_scope
from app.services.overgraph.catalogs import Catalog, catalog_root, open_catalog
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.text_units import load_domain_text_unit
from app.services.overgraph.write import upsert_text_unit

BACKUP_TABLES = ("text_units_dropped", "shared_text_chunks_dropped")

_SELECT = (
    "SELECT u.id, u.scope_type, u.scope_key, u.customer_id, u.document_id, "
    "u.document_version_id, u.section_id, u.ordinal, u.content_hash, u.locator, "
    "u.page_start, u.page_end, u.char_start, u.char_end, u.valid_from, u.valid_to, "
    "c.text AS chunk_text, u.extra "
    "FROM text_units_dropped u "
    "LEFT JOIN shared_text_chunks_dropped c ON c.content_hash = u.content_hash"
)


@dataclass
class ReplayReport:
    """Outcome of a replay. ``mismatches`` must be empty before the backup is removed."""

    rows: int = 0
    replayed: int = 0
    verified: int = 0
    mismatches: list[str] = field(default_factory=list)
    dropped_backup_rows: int = 0
    database: str = ""
    catalog: str = ""
    fingerprint: str = ""

    @property
    def verified_completely(self) -> bool:
        return (
            self.rows > 0
            and self.replayed == self.rows
            and self.verified == self.rows
            and not self.mismatches
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "replayed": self.replayed,
            "verified": self.verified,
            "verified_completely": self.verified_completely,
            "mismatches": self.mismatches[:20],
            "dropped_backup_rows": self.dropped_backup_rows,
            "database": self.database,
            "catalog": self.catalog,
            "fingerprint": self.fingerprint,
        }


def backup_exists(connection: sa.Connection) -> bool:
    inspect = sa.inspect(connection)
    return all(inspect.has_table(name) for name in BACKUP_TABLES)


def load_rows(connection: sa.Connection) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(sa.text(_SELECT)).mappings().all()]


def _timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _scope(row: dict[str, object]):
    customer_id = row["customer_id"]
    if str(row["scope_type"]) == "customer" and customer_id is not None:
        return customer_scope(int(customer_id))  # type: ignore[arg-type]
    return shared_scope()


def _write(row: dict[str, object]) -> TextUnitWrite:
    return TextUnitWrite(
        unit_id=str(row["id"]),
        scope=_scope(row),
        document_id=str(row["document_id"]),
        document_version_id=str(row["document_version_id"]),
        text=str(row["chunk_text"] or ""),
        content_hash=str(row["content_hash"]),
        ordinal=int(row["ordinal"]),  # type: ignore[arg-type]
        section_id=row["section_id"],  # type: ignore[arg-type]
        locator=row["locator"],  # type: ignore[arg-type]
        page_start=row["page_start"],  # type: ignore[arg-type]
        page_end=row["page_end"],  # type: ignore[arg-type]
        char_start=row["char_start"],  # type: ignore[arg-type]
        char_end=row["char_end"],  # type: ignore[arg-type]
        valid_from=_timestamp(row["valid_from"]),
        valid_to=_timestamp(row["valid_to"]),
    )


def fingerprint(rows: list[dict[str, object]], catalog: Catalog, database: str) -> str:
    """Bind a verification to this backup, this database and this catalog directory."""
    digest = hashlib.sha256()
    digest.update(str(database).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(catalog.path).encode("utf-8"))
    digest.update(b"\0")
    for unit_id, content_hash in sorted(
        (str(row["id"]), str(row["content_hash"])) for row in rows
    ):
        digest.update(f"{unit_id}:{content_hash}\n".encode("utf-8"))
    return digest.hexdigest()


def _content_hash_matches(row: dict[str, object]) -> bool:
    text = row["chunk_text"]
    if text is None:
        return False
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest() == str(row["content_hash"])


def _readback_matches(row: dict[str, object], catalog: Catalog) -> bool:
    unit = load_domain_text_unit(catalog, unit_id=str(row["id"]))
    if unit is None:
        return False
    return (
        unit.text == str(row["chunk_text"] or "")
        and unit.content_hash == str(row["content_hash"])
        and unit.document_id == str(row["document_id"])
        and unit.document_version_id == str(row["document_version_id"])
        and unit.ordinal == int(row["ordinal"])  # type: ignore[arg-type]
        and unit.section_id == row["section_id"]
        and unit.locator == row["locator"]
    )


def replay(rows: list[dict[str, object]], catalog: Catalog) -> ReplayReport:
    """Verify, upsert and read back every backup row."""
    report = ReplayReport(rows=len(rows), catalog=str(catalog.path))
    failed: set[str] = set()
    for row in rows:
        unit_id = str(row["id"])
        if not _content_hash_matches(row):
            report.mismatches.append(f"{unit_id}: content_hash does not match stored text")
            failed.add(unit_id)
            continue
        upsert_text_unit(catalog, _write(row))
        report.replayed += 1
    catalog.flush()
    catalog.sync()
    for row in rows:
        unit_id = str(row["id"])
        if unit_id in failed:
            continue
        if _readback_matches(row, catalog):
            report.verified += 1
        else:
            report.mismatches.append(f"{unit_id}: OverGraph read-back does not match backup row")
    return report


def drop_backup(connection: sa.Connection) -> int:
    dropped = sum(
        int(connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one())
        for table in BACKUP_TABLES
    )
    connection.execute(sa.text("DROP TABLE shared_text_chunks_dropped"))
    connection.execute(sa.text("DROP TABLE text_units_dropped"))
    return dropped


def _database_label() -> str:
    return engine.url.render_as_string(hide_password=True)


async def backfill(*, drop_backup_flag: bool, expect_fingerprint: str | None = None) -> dict[str, Any]:
    async with engine.begin() as connection:
        if not await connection.run_sync(backup_exists):
            return {"rows": 0, "note": "no *_dropped backup tables; nothing to replay"}
        rows = await connection.run_sync(load_rows)
        if not rows:
            dropped = await connection.run_sync(drop_backup) if drop_backup_flag else 0
            return {"rows": 0, "dropped_backup_rows": dropped}
        catalog = open_catalog(
            catalog_root(settings.overgraph_dir) / "knowledge",
            kind="knowledge",
            dimension=settings.embedding_dimension,
        )
        try:
            report = replay(rows, catalog)
            report.database = _database_label()
            report.fingerprint = fingerprint(rows, catalog, report.database)
        finally:
            catalog.close()
        if expect_fingerprint is not None and expect_fingerprint != report.fingerprint:
            raise RuntimeError(
                "Refusing --drop-backup: fingerprint does not match this database and catalog "
                f"(expected {expect_fingerprint}, verified {report.fingerprint}). "
                "The graph or the backup changed since verification; the backup tables were kept."
            )
        if drop_backup_flag:
            if not report.verified_completely:
                raise RuntimeError(
                    "Refusing --drop-backup: replay is not verified "
                    f"({report.verified}/{report.rows} rows, "
                    f"{len(report.mismatches)} mismatches). The backup tables were kept."
                )
            report.dropped_backup_rows = await connection.run_sync(drop_backup)
        return report.as_dict()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--drop-backup",
        action="store_true",
        help="Remove the *_dropped tables, only after every row is verified in OverGraph.",
    )
    parser.add_argument(
        "--expect-fingerprint",
        default=None,
        help="Require the verification to bind to this database and catalog fingerprint.",
    )
    args = parser.parse_args()
    try:
        print(json.dumps(
            await backfill(
                drop_backup_flag=args.drop_backup,
                expect_fingerprint=args.expect_fingerprint,
            ),
            ensure_ascii=False,
        ))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
