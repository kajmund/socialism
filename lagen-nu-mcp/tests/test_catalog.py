from lagen_nu_mcp.catalog import (
    CATEGORY_FEEDS,
    doc_type_from_feed_url,
    parse_sitenews_feeds,
    root_feeds,
)

SITENEWS_HTML = """
<dl>
  <dd><a href="https://lagen.nu/dataset/sitenews/feed.atom">atom</a></dd>
  <dd><a href="https://lagen.nu/dataset/sfs/feed.atom?rdf_type=type/lag">atom</a></dd>
  <dd><a href="https://lagen.nu/dataset/sfs/feed.atom">atom</a></dd>
  <dd><a href="https://lagen.nu/dataset/dv/feed.atom?rpubl_rattsfallspublikation=nja">atom</a></dd>
  <dd><a href="https://lagen.nu/dataset/forarbeten/feed.atom">atom</a></dd>
</dl>
"""


def test_root_feeds_are_the_six_datasets() -> None:
    feeds = root_feeds()
    assert [feed.doc_type for feed in feeds] == [
        "sfs",
        "dv",
        "forarbete",
        "myndfs",
        "myndprax",
        "keyword",
    ]
    assert {feed.url for feed in feeds} == set(CATEGORY_FEEDS.values())


def test_sitenews_discovery_skips_sitenews_and_dedupes() -> None:
    feeds = parse_sitenews_feeds(SITENEWS_HTML)
    urls = [feed.url for feed in feeds]
    assert "https://lagen.nu/dataset/sitenews/feed.atom" not in urls
    assert urls == [
        "https://lagen.nu/dataset/sfs/feed.atom?rdf_type=type/lag",
        "https://lagen.nu/dataset/sfs/feed.atom",
        "https://lagen.nu/dataset/dv/feed.atom?rpubl_rattsfallspublikation=nja",
        "https://lagen.nu/dataset/forarbeten/feed.atom",
    ]
    assert feeds[3].doc_type == "forarbete"


def test_doc_type_from_filtered_feed() -> None:
    assert (
        doc_type_from_feed_url(
            "https://lagen.nu/dataset/dv/feed.atom?rpubl_rattsfallspublikation=nja"
        )
        == "dv"
    )
