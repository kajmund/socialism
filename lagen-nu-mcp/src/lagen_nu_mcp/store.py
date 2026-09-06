"""feed_state + pending_fetch stores. Memory for tests; Postgres for cron."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class FeedState:
    feed_url: str
    last_polled_at: datetime | None
    last_seen_entry_updated: datetime | None


@dataclass(frozen=True)
class PendingItem:
    url: str
    atom_id: str
    feed_url: str
    doc_type: str
    atom_updated: datetime
    title: str | None


@dataclass(frozen=True)
class CachedDocument:
    url: str
    doc_type: str
    sfs_nr: str | None
    feed_source: str | None
    atom_updated: datetime | None
    content_hash: str
    format: str
    raw_content: str


@dataclass(frozen=True)
class CachedVersion:
    sfs_nr: str
    amending_sfs: str
    konsolidering_url: str | None
    content_hash: str
    raw_content: str | None
    is_current: bool


@dataclass(frozen=True)
class CachedParagraph:
    url: str
    anchor: str
    label: str | None
    text: str


class Store(Protocol):
    def get_feed_state(self, feed_url: str) -> FeedState | None: ...

    def upsert_feed_state(self, state: FeedState) -> None: ...

    def enqueue_pending(self, item: PendingItem) -> bool: ...

    def list_pending(self) -> tuple[PendingItem, ...]: ...

    def dequeue_pending(self, url: str) -> None: ...

    def get_document(self, url: str) -> CachedDocument | None: ...

    def upsert_document(self, document: CachedDocument) -> None: ...

    def replace_paragraphs(self, url: str, paragraphs: tuple[CachedParagraph, ...]) -> None: ...

    def get_current_version(self, sfs_nr: str) -> CachedVersion | None: ...

    def upsert_version(self, version: CachedVersion) -> None: ...

    def demote_current_version(self, sfs_nr: str, konsolidering_url: str) -> CachedVersion | None: ...


class MemoryStore:
    def __init__(self) -> None:
        self.feed_state: dict[str, FeedState] = {}
        self.pending: dict[str, PendingItem] = {}
        self.documents: dict[str, CachedDocument] = {}
        self.versions: dict[tuple[str, str], CachedVersion] = {}
        self.paragraphs: dict[str, list[CachedParagraph]] = {}

    def get_feed_state(self, feed_url: str) -> FeedState | None:
        return self.feed_state.get(feed_url)

    def upsert_feed_state(self, state: FeedState) -> None:
        self.feed_state[state.feed_url] = state

    def enqueue_pending(self, item: PendingItem) -> bool:
        existing = self.pending.get(item.url)
        if existing is None or item.atom_updated > existing.atom_updated:
            self.pending[item.url] = item
            return True
        return False

    def list_pending(self) -> tuple[PendingItem, ...]:
        return tuple(self.pending.values())

    def dequeue_pending(self, url: str) -> None:
        self.pending.pop(url, None)

    def get_document(self, url: str) -> CachedDocument | None:
        return self.documents.get(url)

    def upsert_document(self, document: CachedDocument) -> None:
        self.documents[document.url] = document

    def replace_paragraphs(self, url: str, paragraphs: tuple[CachedParagraph, ...]) -> None:
        self.paragraphs[url] = list(paragraphs)

    def get_current_version(self, sfs_nr: str) -> CachedVersion | None:
        for version in self.versions.values():
            if version.sfs_nr == sfs_nr and version.is_current:
                return version
        return None

    def upsert_version(self, version: CachedVersion) -> None:
        self.versions[(version.sfs_nr, version.amending_sfs)] = version

    def demote_current_version(self, sfs_nr: str, konsolidering_url: str) -> CachedVersion | None:
        current = self.get_current_version(sfs_nr)
        if current is None:
            return None
        demoted = CachedVersion(
            sfs_nr=current.sfs_nr,
            amending_sfs=current.amending_sfs,
            konsolidering_url=konsolidering_url,
            content_hash=current.content_hash,
            raw_content=current.raw_content,
            is_current=False,
        )
        self.versions[(sfs_nr, current.amending_sfs)] = demoted
        return demoted


class PostgresStore:
    def __init__(self, conn) -> None:
        self._conn = conn

    def get_feed_state(self, feed_url: str) -> FeedState | None:
        row = self._conn.execute(
            """
            select feed_url, last_polled_at, last_seen_entry_updated
            from lagen_nu.feed_state
            where feed_url = %s
            """,
            (feed_url,),
        ).fetchone()
        if row is None:
            return None
        return FeedState(
            feed_url=row[0],
            last_polled_at=row[1],
            last_seen_entry_updated=row[2],
        )

    def upsert_feed_state(self, state: FeedState) -> None:
        self._conn.execute(
            """
            insert into lagen_nu.feed_state (
                feed_url, last_polled_at, last_seen_entry_updated
            ) values (%s, %s, %s)
            on conflict (feed_url) do update set
                last_polled_at = excluded.last_polled_at,
                last_seen_entry_updated = excluded.last_seen_entry_updated
            """,
            (state.feed_url, state.last_polled_at, state.last_seen_entry_updated),
        )

    def enqueue_pending(self, item: PendingItem) -> bool:
        row = self._conn.execute(
            """
            insert into lagen_nu.pending_fetch (
                url, atom_id, feed_url, doc_type, atom_updated, title
            ) values (%s, %s, %s, %s, %s, %s)
            on conflict (url) do update set
                atom_id = excluded.atom_id,
                feed_url = excluded.feed_url,
                doc_type = excluded.doc_type,
                atom_updated = excluded.atom_updated,
                title = excluded.title,
                enqueued_at = now()
            where excluded.atom_updated > lagen_nu.pending_fetch.atom_updated
            returning url
            """,
            (
                item.url,
                item.atom_id,
                item.feed_url,
                item.doc_type,
                item.atom_updated,
                item.title,
            ),
        ).fetchone()
        return row is not None

    def list_pending(self) -> tuple[PendingItem, ...]:
        rows = self._conn.execute(
            """
            select url, atom_id, feed_url, doc_type, atom_updated, title
            from lagen_nu.pending_fetch
            order by atom_updated desc
            """
        ).fetchall()
        return tuple(
            PendingItem(
                url=row[0],
                atom_id=row[1],
                feed_url=row[2],
                doc_type=row[3],
                atom_updated=row[4],
                title=row[5],
            )
            for row in rows
        )

    def dequeue_pending(self, url: str) -> None:
        self._conn.execute(
            "delete from lagen_nu.pending_fetch where url = %s",
            (url,),
        )

    def get_document(self, url: str) -> CachedDocument | None:
        row = self._conn.execute(
            """
            select url, doc_type, sfs_nr, feed_source, atom_updated,
                   content_hash, format, raw_content
            from lagen_nu.documents
            where url = %s
            """,
            (url,),
        ).fetchone()
        if row is None:
            return None
        return CachedDocument(
            url=row[0],
            doc_type=row[1],
            sfs_nr=row[2],
            feed_source=row[3],
            atom_updated=row[4],
            content_hash=row[5],
            format=row[6],
            raw_content=row[7],
        )

    def upsert_document(self, document: CachedDocument) -> None:
        self._conn.execute(
            """
            insert into lagen_nu.documents (
                url, doc_type, sfs_nr, feed_source, atom_updated,
                content_hash, fetched_at, format, raw_content
            ) values (%s, %s, %s, %s, %s, %s, now(), %s, %s)
            on conflict (url) do update set
                doc_type = excluded.doc_type,
                sfs_nr = excluded.sfs_nr,
                feed_source = excluded.feed_source,
                atom_updated = excluded.atom_updated,
                content_hash = excluded.content_hash,
                fetched_at = now(),
                format = excluded.format,
                raw_content = excluded.raw_content
            """,
            (
                document.url,
                document.doc_type,
                document.sfs_nr,
                document.feed_source,
                document.atom_updated,
                document.content_hash,
                document.format,
                document.raw_content,
            ),
        )

    def replace_paragraphs(self, url: str, paragraphs: tuple[CachedParagraph, ...]) -> None:
        self._conn.execute("delete from lagen_nu.paragraphs where url = %s", (url,))
        for paragraph in paragraphs:
            self._conn.execute(
                """
                insert into lagen_nu.paragraphs (url, anchor, label, text)
                values (%s, %s, %s, %s)
                """,
                (paragraph.url, paragraph.anchor, paragraph.label, paragraph.text),
            )

    def get_current_version(self, sfs_nr: str) -> CachedVersion | None:
        row = self._conn.execute(
            """
            select sfs_nr, amending_sfs, konsolidering_url, content_hash,
                   raw_content, is_current
            from lagen_nu.document_versions
            where sfs_nr = %s and is_current
            """,
            (sfs_nr,),
        ).fetchone()
        if row is None:
            return None
        return CachedVersion(
            sfs_nr=row[0],
            amending_sfs=row[1],
            konsolidering_url=row[2],
            content_hash=row[3],
            raw_content=row[4],
            is_current=row[5],
        )

    def upsert_version(self, version: CachedVersion) -> None:
        self._conn.execute(
            """
            insert into lagen_nu.document_versions (
                sfs_nr, amending_sfs, konsolidering_url, content_hash,
                raw_content, is_current, fetched_at
            ) values (%s, %s, %s, %s, %s, %s, now())
            on conflict (sfs_nr, amending_sfs) do update set
                konsolidering_url = excluded.konsolidering_url,
                content_hash = excluded.content_hash,
                raw_content = excluded.raw_content,
                is_current = excluded.is_current,
                fetched_at = now()
            """,
            (
                version.sfs_nr,
                version.amending_sfs,
                version.konsolidering_url,
                version.content_hash,
                version.raw_content,
                version.is_current,
            ),
        )

    def demote_current_version(self, sfs_nr: str, konsolidering_url: str) -> CachedVersion | None:
        row = self._conn.execute(
            """
            update lagen_nu.document_versions
            set is_current = false, konsolidering_url = %s
            where sfs_nr = %s and is_current
            returning sfs_nr, amending_sfs, konsolidering_url, content_hash,
                      raw_content, is_current
            """,
            (konsolidering_url, sfs_nr),
        ).fetchone()
        if row is None:
            return None
        return CachedVersion(
            sfs_nr=row[0],
            amending_sfs=row[1],
            konsolidering_url=row[2],
            content_hash=row[3],
            raw_content=row[4],
            is_current=row[5],
        )


def connect_postgres(database_url: str):
    import psycopg

    return psycopg.connect(database_url, autocommit=True)
