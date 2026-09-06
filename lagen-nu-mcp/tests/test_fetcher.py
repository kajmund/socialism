from datetime import datetime, timezone

from lagen_nu_mcp.fetcher import fetch_item, fetch_pending, konsolidering_url
from lagen_nu_mcp.http import HttpResponse
from lagen_nu_mcp.store import MemoryStore, PendingItem


def _item() -> PendingItem:
    return PendingItem(
        url="https://lagen.nu/2017:193",
        atom_id="https://lagen.nu/2017:193",
        feed_url="https://lagen.nu/dataset/sfs/feed.atom",
        doc_type="sfs",
        atom_updated=datetime(2026, 9, 3, 6, 17, 58, tzinfo=timezone.utc),
        title="Förordning (2017:193)",
    )


class FakeClient:
    def __init__(self, body: str, content_type: str = "text/html") -> None:
        self.body = body
        self.content_type = content_type

    def get(self, url: str, *, accept: str) -> HttpResponse:
        return HttpResponse(
            url=url,
            status=200,
            content_type=self.content_type,
            body=self.body,
        )


def test_fetch_stores_document_and_paragraphs(sfs_html: str) -> None:
    store = MemoryStore()
    store.enqueue_pending(_item())
    result = fetch_item(_item(), store=store, client=FakeClient(sfs_html))
    assert result.format == "html"
    assert result.rotated_version is False
    assert "https://lagen.nu/2017:193" not in store.pending
    doc = store.get_document("https://lagen.nu/2017:193")
    assert doc is not None
    assert doc.sfs_nr == "2017:193"
    assert doc.format == "html"
    paragraphs = store.paragraphs["https://lagen.nu/2017:193"]
    assert {p.anchor for p in paragraphs} >= {"P1", "P3a"}
    current = store.get_current_version("2017:193")
    assert current is not None
    assert current.amending_sfs == "2026:1735"
    assert current.is_current


def test_andring_change_rotates_version(sfs_html: str) -> None:
    store = MemoryStore()
    fetch_item(_item(), store=store, client=FakeClient(sfs_html))
    newer = sfs_html.replace("SFS 2026:1735", "SFS 2026:1800", 1)
    store.enqueue_pending(_item())
    result = fetch_item(_item(), store=store, client=FakeClient(newer))
    assert result.rotated_version is True
    current = store.get_current_version("2017:193")
    assert current is not None
    assert current.amending_sfs == "2026:1800"
    previous = store.versions[("2017:193", "2026:1735")]
    assert previous.is_current is False
    assert previous.konsolidering_url == konsolidering_url("2017:193", "2026:1735")
    assert previous.raw_content is not None


def test_fetch_pending_counts_failures(sfs_html: str) -> None:
    store = MemoryStore()
    store.enqueue_pending(_item())

    class Boom:
        def get(self, url: str, *, accept: str) -> HttpResponse:
            raise RuntimeError("boom")

    run = fetch_pending(store, Boom())  # type: ignore[arg-type]
    assert run.fetched == 0
    assert run.failed == 1
    assert store.pending  # left in queue
