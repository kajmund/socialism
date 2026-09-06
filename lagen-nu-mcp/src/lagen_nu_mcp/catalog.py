"""lagen.nu Atom feed catalog.

Default (`roots`) polls the six dataset feeds so we cover every document
without requesting the ~60 overlapping filtered views on /dataset/sitenews.
`all` discovers every feed.atom link on that page except sitenews itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

if TYPE_CHECKING:
    from lagen_nu_mcp.http import HttpClient

SITENEWS_URL = "https://lagen.nu/dataset/sitenews"

CATEGORY_FEEDS: dict[str, str] = {
    "sfs": "https://lagen.nu/dataset/sfs/feed.atom",
    "dv": "https://lagen.nu/dataset/dv/feed.atom",
    "forarbeten": "https://lagen.nu/dataset/forarbeten/feed.atom",
    "myndfs": "https://lagen.nu/dataset/myndfs/feed.atom",
    "myndprax": "https://lagen.nu/dataset/myndprax/feed.atom",
    "keyword": "https://lagen.nu/dataset/keyword/feed.atom",
}

_ATOM_HREF = re.compile(
    r'href="(https://lagen\.nu/dataset/[^"]+/feed\.atom[^"]*)"'
)
_DATASET_PATH = re.compile(r"/dataset/([^/]+)/")

FeedMode = Literal["roots", "all"]


@dataclass(frozen=True)
class Feed:
    url: str
    doc_type: str


def doc_type_from_feed_url(url: str) -> str:
    match = _DATASET_PATH.search(urlparse(url).path)
    if not match:
        raise ValueError(f"cannot infer doc_type from feed URL: {url}")
    dataset = match.group(1)
    if dataset == "forarbeten":
        return "forarbete"
    return dataset


def root_feeds() -> tuple[Feed, ...]:
    return tuple(
        Feed(url=url, doc_type=doc_type_from_feed_url(url))
        for url in CATEGORY_FEEDS.values()
    )


def parse_sitenews_feeds(html: str) -> tuple[Feed, ...]:
    seen: set[str] = set()
    feeds: list[Feed] = []
    for url in _ATOM_HREF.findall(html):
        if url in seen:
            continue
        doc_type = doc_type_from_feed_url(url)
        if doc_type == "sitenews":
            continue
        seen.add(url)
        feeds.append(Feed(url=url, doc_type=doc_type))
    return tuple(feeds)


def load_feeds(mode: FeedMode, client: HttpClient | None = None) -> tuple[Feed, ...]:
    if mode == "roots":
        return root_feeds()
    if client is None:
        raise ValueError("HttpClient is required when feed mode is 'all'")
    html = client.get_text(SITENEWS_URL, accept="text/html")
    return parse_sitenews_feeds(html)
