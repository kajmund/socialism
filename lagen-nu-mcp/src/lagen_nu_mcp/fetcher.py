"""Drain pending_fetch, store document bodies, rotate SFS versions."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from lagen_nu_mcp.document import ParsedDocument, parse_response
from lagen_nu_mcp.http import HttpClient
from lagen_nu_mcp.store import (
    CachedDocument,
    CachedParagraph,
    CachedVersion,
    PendingItem,
    Store,
)

log = logging.getLogger(__name__)

DOCUMENT_ACCEPT = (
    "application/json, application/ld+json;q=0.9, "
    "application/xhtml+xml;q=0.8, text/html;q=0.7"
)


@dataclass(frozen=True)
class FetchItemResult:
    url: str
    format: str
    rotated_version: bool


@dataclass(frozen=True)
class FetchRun:
    fetched: int
    failed: int
    rotated: int


def konsolidering_url(sfs_nr: str, amending_sfs: str) -> str:
    return f"https://lagen.nu/{sfs_nr}/konsolidering/{amending_sfs}"


def _apply_sfs_version(store: Store, parsed: ParsedDocument) -> bool:
    if parsed.sfs_nr is None or parsed.amending_sfs is None:
        return False
    current = store.get_current_version(parsed.sfs_nr)
    if current is None:
        store.upsert_version(
            CachedVersion(
                sfs_nr=parsed.sfs_nr,
                amending_sfs=parsed.amending_sfs,
                konsolidering_url=None,
                content_hash=parsed.content_hash,
                raw_content=parsed.raw_content,
                is_current=True,
            )
        )
        return False
    if current.amending_sfs == parsed.amending_sfs:
        store.upsert_version(
            CachedVersion(
                sfs_nr=current.sfs_nr,
                amending_sfs=current.amending_sfs,
                konsolidering_url=current.konsolidering_url,
                content_hash=parsed.content_hash,
                raw_content=parsed.raw_content,
                is_current=True,
            )
        )
        return False
    store.demote_current_version(
        parsed.sfs_nr,
        konsolidering_url(parsed.sfs_nr, current.amending_sfs),
    )
    store.upsert_version(
        CachedVersion(
            sfs_nr=parsed.sfs_nr,
            amending_sfs=parsed.amending_sfs,
            konsolidering_url=None,
            content_hash=parsed.content_hash,
            raw_content=parsed.raw_content,
            is_current=True,
        )
    )
    log.info(
        "sfs version %s %s -> %s",
        parsed.sfs_nr,
        current.amending_sfs,
        parsed.amending_sfs,
    )
    return True


def fetch_item(item: PendingItem, *, store: Store, client: HttpClient) -> FetchItemResult:
    response = client.get(item.url, accept=DOCUMENT_ACCEPT)
    parsed = parse_response(item.url, response)
    store.upsert_document(
        CachedDocument(
            url=item.url,
            doc_type=item.doc_type,
            sfs_nr=parsed.sfs_nr,
            feed_source=item.feed_url,
            atom_updated=item.atom_updated,
            content_hash=parsed.content_hash,
            format=parsed.format,
            raw_content=parsed.raw_content,
        )
    )
    store.replace_paragraphs(
        item.url,
        tuple(
            CachedParagraph(
                url=item.url,
                anchor=paragraph.anchor,
                label=paragraph.label,
                text=paragraph.text,
            )
            for paragraph in parsed.paragraphs
        ),
    )
    rotated = False
    if item.doc_type == "sfs":
        rotated = _apply_sfs_version(store, parsed)
    store.dequeue_pending(item.url)
    log.info(
        "fetch %s format=%s paragraphs=%s rotated=%s",
        item.url,
        parsed.format,
        len(parsed.paragraphs),
        rotated,
    )
    return FetchItemResult(url=item.url, format=parsed.format, rotated_version=rotated)


def fetch_pending(
    store: Store,
    client: HttpClient,
    *,
    limit: int | None = None,
) -> FetchRun:
    items = store.list_pending()
    if limit is not None:
        items = items[:limit]
    fetched = 0
    failed = 0
    rotated = 0
    for item in items:
        try:
            result = fetch_item(item, store=store, client=client)
        except Exception:
            failed += 1
            log.exception("fetch failed %s", item.url)
            continue
        fetched += 1
        if result.rotated_version:
            rotated += 1
    log.info("fetch done fetched=%s failed=%s rotated=%s", fetched, failed, rotated)
    return FetchRun(fetched=fetched, failed=failed, rotated=rotated)
