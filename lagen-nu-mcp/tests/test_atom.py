from datetime import datetime, timezone

import pytest

from lagen_nu_mcp.atom import AtomError, parse_atom


def test_parse_extracts_id_and_updated(sfs_atom: str) -> None:
    feed = parse_atom(sfs_atom)
    assert feed.title == "Alla författningar"
    assert len(feed.entries) == 2
    first = feed.entries[0]
    assert first.atom_id == "https://lagen.nu/2017:193"
    assert first.url == "https://lagen.nu/2017:193"
    assert first.updated == datetime(2026, 9, 3, 6, 17, 58, tzinfo=timezone.utc)
    assert first.title is not None
    assert "2017:193" in first.title


def test_parse_accepts_zulu_timestamp() -> None:
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>https://lagen.nu/2026:1490</id>
        <updated>2026-09-05T12:54:12.273160Z</updated>
      </entry>
    </feed>
    """
    feed = parse_atom(xml)
    assert feed.entries[0].updated.tzinfo is not None


def test_parse_rejects_naive_timestamp() -> None:
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>https://lagen.nu/2020:1</id>
        <updated>2026-09-03T06:17:58</updated>
      </entry>
    </feed>
    """
    with pytest.raises(AtomError, match="timezone-aware"):
        parse_atom(xml)


def test_parse_rejects_missing_id() -> None:
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <updated>2026-09-03T06:17:58-00:00</updated>
      </entry>
    </feed>
    """
    with pytest.raises(AtomError, match="id"):
        parse_atom(xml)
