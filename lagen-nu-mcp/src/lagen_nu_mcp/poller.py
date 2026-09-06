"""Hourly feed poller: Atom id+updated → pending_fetch, watermark in feed_state."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from lagen_nu_mcp.atom import parse_atom
from lagen_nu_mcp.catalog import Feed
from lagen_nu_mcp.http import HttpClient
from lagen_nu_mcp.store import FeedState, PendingItem, Store

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedPollResult:
    feed_url: str
    doc_type: str
    seen: int
    new: int
    watermark: datetime | None


@dataclass(frozen=True)
class PollRun:
    results: tuple[FeedPollResult, ...]

    @property
    def new_total(self) -> int:
        return sum(item.new for item in self.results)

    @property
    def seen_total(self) -> int:
        return sum(item.seen for item in self.results)


def _new_entries(entries, watermark: datetime | None):
    if watermark is None:
        return list(entries)
    return [entry for entry in entries if entry.updated > watermark]


def poll_feed(
    feed: Feed,
    *,
    store: Store,
    client: HttpClient,
    now: datetime | None = None,
) -> FeedPollResult:
    polled_at = now or datetime.now(UTC)
    xml = client.get_text(feed.url, accept="application/atom+xml, application/xml;q=0.9")
    parsed = parse_atom(xml)
    state = store.get_feed_state(feed.url)
    watermark = state.last_seen_entry_updated if state else None
    fresh = _new_entries(parsed.entries, watermark)

    for entry in fresh:
        store.enqueue_pending(
            PendingItem(
                url=entry.url,
                atom_id=entry.atom_id,
                feed_url=feed.url,
                doc_type=feed.doc_type,
                atom_updated=entry.updated,
                title=entry.title,
            )
        )

    newest = max((entry.updated for entry in parsed.entries), default=watermark)
    store.upsert_feed_state(
        FeedState(
            feed_url=feed.url,
            last_polled_at=polled_at,
            last_seen_entry_updated=newest,
        )
    )

    result = FeedPollResult(
        feed_url=feed.url,
        doc_type=feed.doc_type,
        seen=len(parsed.entries),
        new=len(fresh),
        watermark=newest,
    )
    log.info(
        "poll %s new=%s seen=%s watermark=%s",
        feed.doc_type,
        result.new,
        result.seen,
        result.watermark.isoformat() if result.watermark else None,
    )
    return result


def poll_feeds(
    feeds: tuple[Feed, ...],
    *,
    store: Store,
    client: HttpClient,
) -> PollRun:
    results = tuple(poll_feed(feed, store=store, client=client) for feed in feeds)
    run = PollRun(results=results)
    log.info("poll done new=%s seen=%s feeds=%s", run.new_total, run.seen_total, len(results))
    return run
