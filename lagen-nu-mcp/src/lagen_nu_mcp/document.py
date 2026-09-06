"""Parse lagen.nu document bodies (JSON if offered, otherwise the HTML page)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from lagen_nu_mcp.http import HttpResponse

SFS_IN_PATH = re.compile(r"^/(\d{4}:\d+)(?:/|$)")
SFS_LABEL = re.compile(r"SFS\s+(\d{4}:\d+)", re.I)
ANDRING = re.compile(
    r"<dt>\s*Ändring införd t\.o\.m\.\s*</dt>\s*<dd>\s*SFS\s+(\d{4}:\d+)",
    re.I,
)
PARAGRAF = re.compile(
    r'<section class="paragraf" id="(P[^"]+)"[^>]*>'
    r'.*?<span class="n">([^<]+)</span>'
    r'.*?<div class="paragraf-body">(.*?)</div>\s*</section>',
    re.S,
)
H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
TAGS = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


class DocumentParseError(ValueError):
    pass


@dataclass(frozen=True)
class Paragraph:
    anchor: str
    label: str | None
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    format: str
    raw_content: str
    content_hash: str
    sfs_nr: str | None
    amending_sfs: str | None
    title: str | None
    paragraphs: tuple[Paragraph, ...]


def content_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def strip_tags(html: str) -> str:
    return WS.sub(" ", TAGS.sub(" ", html)).strip()


def sfs_nr_from_url(url: str) -> str | None:
    from urllib.parse import urlparse

    match = SFS_IN_PATH.match(urlparse(url).path)
    return match.group(1) if match else None


def classify_format(response: HttpResponse) -> str:
    ctype = response.content_type.lower()
    if ctype in {"application/json", "application/ld+json"}:
        return "json"
    if "xml" in ctype:
        return "rdf" if "rdf" in ctype else "html"
    body = response.body.lstrip()
    if ctype.endswith("json") or body[:1] in "{[":
        try:
            json.loads(response.body)
        except json.JSONDecodeError:
            return "html"
        return "json"
    return "html"


def parse_html_document(url: str, html: str) -> ParsedDocument:
    sfs_nr = sfs_nr_from_url(url)
    if sfs_nr is None:
        eyebrow = SFS_LABEL.search(html)
        sfs_nr = eyebrow.group(1) if eyebrow else None

    andring = ANDRING.search(html)
    amending = andring.group(1) if andring else sfs_nr

    h1 = H1.search(html)
    title = strip_tags(h1.group(1)) if h1 else None

    paragraphs: list[Paragraph] = []
    for match in PARAGRAF.finditer(html):
        text = strip_tags(match.group(3))
        if not text:
            continue
        paragraphs.append(
            Paragraph(anchor=match.group(1), label=match.group(2).strip(), text=text)
        )

    return ParsedDocument(
        format="html",
        raw_content=html,
        content_hash=content_hash(html),
        sfs_nr=sfs_nr,
        amending_sfs=amending,
        title=title,
        paragraphs=tuple(paragraphs),
    )


def parse_json_document(url: str, raw: str) -> ParsedDocument:
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DocumentParseError(f"Accept promised JSON but body is invalid: {exc}") from exc
    return ParsedDocument(
        format="json",
        raw_content=raw,
        content_hash=content_hash(raw),
        sfs_nr=sfs_nr_from_url(url),
        amending_sfs=sfs_nr_from_url(url),
        title=None,
        paragraphs=(),
    )


def parse_response(url: str, response: HttpResponse) -> ParsedDocument:
    kind = classify_format(response)
    if kind == "json":
        return parse_json_document(url, response.body)
    return parse_html_document(url, response.body)
