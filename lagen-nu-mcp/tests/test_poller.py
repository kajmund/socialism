from datetime import datetime, timezone

from lagen_nu_mcp.atom import parse_atom
from lagen_nu_mcp.catalog import Feed
from lagen_nu_mcp.poller import poll_feed
from lagen_nu_mcp.store import MemoryStore


class FakeClient:
    def __init__(self, body: str) -> None:
        self.body = body
        self.urls: list[str] = []

    def get_text(self, url: str, *, accept: str) -> str:
        self.urls.append(url)
        return self.body


SFS = Feed(url="https://lagen.nu/dataset/sfs/feed.atom", doc_type="sfs")


def test_first_poll_enqueues_every_entry(sfs_atom: str) -> None:
    store = MemoryStore()
    result = poll_feed(SFS, store=store, client=FakeClient(sfs_atom))
    assert result.seen == 2
    assert result.new == 2
    assert set(store.pending) == {
        "https://lagen.nu/2017:193",
        "https://lagen.nu/1999:99",
    }
    state = store.get_feed_state(SFS.url)
    assert state is not None
    assert state.last_seen_entry_updated == datetime(
        2026, 9, 3, 6, 17, 58, tzinfo=timezone.utc
    )


def test_second_poll_is_idempotent(sfs_atom: str) -> None:
    store = MemoryStore()
    client = FakeClient(sfs_atom)
    poll_feed(SFS, store=store, client=client)
    result = poll_feed(SFS, store=store, client=client)
    assert result.new == 0
    assert result.seen == 2
    assert len(store.pending) == 2


def test_newer_updated_enqueues_only_that_entry(sfs_atom: str) -> None:
    store = MemoryStore()
    poll_feed(SFS, store=store, client=FakeClient(sfs_atom))
    parsed = parse_atom(sfs_atom)
    assert parsed.entries[1].atom_id == "https://lagen.nu/1999:99"
    bumped = sfs_atom.replace(
        "<updated>2026-01-01T00:00:00-00:00</updated>",
        "<updated>2026-09-04T08:00:00-00:00</updated>",
        1,
    )
    result = poll_feed(SFS, store=store, client=FakeClient(bumped))
    assert result.new == 1
    assert store.pending["https://lagen.nu/1999:99"].atom_updated == datetime(
        2026, 9, 4, 8, 0, 0, tzinfo=timezone.utc
    )


def test_same_document_from_two_feeds_is_one_pending_row(sfs_atom: str) -> None:
    store = MemoryStore()
    poll_feed(SFS, store=store, client=FakeClient(sfs_atom))
    lag_feed = Feed(
        url="https://lagen.nu/dataset/sfs/feed.atom?rdf_type=type/lag",
        doc_type="sfs",
    )
    poll_feed(lag_feed, store=store, client=FakeClient(sfs_atom))
    assert len(store.pending) == 2
