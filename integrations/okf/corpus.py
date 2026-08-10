"""Load and search Opinionssimulator OKF operator manuals (knowledge/manual)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WORD_RE = re.compile(r"[\wåäöÅÄÖ]+", re.UNICODE)


@dataclass(frozen=True)
class Guide:
    slug: str
    path: Path
    title: str
    description: str
    tags: tuple[str, ...]
    body: str

    @property
    def text(self) -> str:
        return f"# {self.title}\n\n{self.body.strip()}"


def _parse_frontmatter(raw: str) -> tuple[dict[str, str | list[str]], str]:
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    block = match.group(1)
    body = raw[match.end() :]
    meta: dict[str, str | list[str]] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            tags = [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]
            meta[key] = tags
        else:
            meta[key] = value.strip("\"'")
    return meta, body


def _tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text) if len(w) >= -1}


def load_guides(manual_root: Path) -> list[Guide]:
    root = manual_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"OKF manual root not found: {root}")

    guides: list[Guide] = []
    for path in sorted(root.glob("*.md")):
        if path.name in {"index.md", "log.md"}:
            continue
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        guide_type = meta.get("type")
        if guide_type and guide_type != "guide":
            continue
        title = str(meta.get("title") or path.stem.replace("-", " ").title())
        description = str(meta.get("description") or "")
        tags_raw = meta.get("tags")
        if isinstance(tags_raw, list):
            tags = tuple(str(t) for t in tags_raw)
        else:
            tags = ()
        guides.append(
            Guide(
                slug=path.stem,
                path=path,
                title=title,
                description=description,
                tags=tags,
                body=body.strip(),
            )
        )
    return guides


def search_guides(guides: list[Guide], query: str, *, limit: int = 3) -> list[Guide]:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return guides[:limit]

    scored: list[tuple[int, Guide]] = []
    for guide in guides:
        hay = " ".join(
            [guide.title, guide.description, guide.body, " ".join(guide.tags)]
        ).lower()
        hay_tokens = _tokenize(hay)
        overlap = len(q_tokens & hay_tokens)
        if overlap == 0:
            continue
        bonus = 0
        for token in q_tokens:
            if token in guide.slug.replace("-", " "):
                bonus += 2
            if token in guide.title.lower():
                bonus += 1
        scored.append((overlap + bonus, guide))

    scored.sort(key=lambda pair: (-pair[0], pair[1].title))
    return [guide for _, guide in scored[:limit]]


def format_context(guides: list[Guide]) -> str:
    if not guides:
        return "(Inga matchande manualavsnitt hittades.)"
    parts: list[str] = []
    for guide in guides:
        parts.append(f"## {guide.title}\n\n{guide.body.strip()}")
    return "\n\n---\n\n".join(parts)
