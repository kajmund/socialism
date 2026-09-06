"""Parse lagen.nu Atom feeds. Only <id> and <updated> are required per entry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from xml.etree import ElementTree

ATOM_NS = "http://www.w3.org/2005/Atom"
NS = {"atom": ATOM_NS}


class AtomError(ValueError):
    pass


@dataclass(frozen=True)
class AtomEntry:
    atom_id: str
    updated: datetime
    title: str | None
    url: str


@dataclass(frozen=True)
class AtomFeed:
    feed_id: str | None
    title: str | None
    updated: datetime | None
    entries: tuple[AtomEntry, ...]


def _child_text(parent: ElementTree.Element, tag: str) -> str | None:
    node = parent.find(f"atom:{tag}", NS)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _parse_dt(value: str, *, field: str) -> datetime:
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AtomError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise AtomError(f"{field} must be timezone-aware: {value!r}")
    return parsed


def parse_atom(xml: str) -> AtomFeed:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise AtomError(f"invalid Atom XML: {exc}") from exc

    if root.tag != f"{{{ATOM_NS}}}feed":
        raise AtomError(f"root element is {root.tag}, expected Atom feed")

    entries: list[AtomEntry] = []
    for node in root.findall("atom:entry", NS):
        atom_id = _child_text(node, "id")
        updated_raw = _child_text(node, "updated")
        if not atom_id or not updated_raw:
            raise AtomError("entry missing required <id> or <updated>")
        entries.append(
            AtomEntry(
                atom_id=atom_id,
                updated=_parse_dt(updated_raw, field="entry.updated"),
                title=_child_text(node, "title"),
                url=atom_id,
            )
        )

    feed_updated = _child_text(root, "updated")
    return AtomFeed(
        feed_id=_child_text(root, "id"),
        title=_child_text(root, "title"),
        updated=_parse_dt(feed_updated, field="feed.updated") if feed_updated else None,
        entries=tuple(entries),
    )
