"""Parallel campaign-message variant generation + URL summarize helpers."""

from __future__ import annotations

import asyncio
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.llm import complete_text
from app.schemas.domain import (
    GenerateVariantsRequest,
    MessageType,
    MessageVariant,
    MessageVariantOut,
)
from app.services.prompt_catalog import render_prompt

VARIANT_KEYS: list[tuple[MessageVariant, str, str]] = [
    ("analytical", "Professionell / analytisk", "messages.variant.analytical"),
    ("narrative", "Personlig / berättande", "messages.variant.narrative"),
    ("concise", "Kort / koncis", "messages.variant.concise"),
]

_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "iframe",
        "template",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
        "select",
        "option",
        "label",
    }
)
_CONTENT_TAGS = frozenset({"article", "main"})
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class _TextExtractor(HTMLParser):
    """Prefer article/main body; fall back to page text. Capture title + meta."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._in_title = 0
        self._content_depth = 0
        self._title_chunks: list[str] = []
        self._meta: dict[str, str] = {}
        self._content_chunks: list[str] = []
        self._body_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            self._capture_meta(attr)
            return
        if tag == "title":
            self._in_title += 1
            return
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag in _CONTENT_TAGS:
            self._content_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title > 0:
            self._in_title -= 1
            return
        if tag in _SKIP_TAGS and self._skip > 0:
            self._skip -= 1
            return
        if tag in _CONTENT_TAGS and self._content_depth > 0:
            self._content_depth -= 1

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title > 0:
            self._title_chunks.append(text)
            return
        if self._skip > 0:
            return
        if self._content_depth > 0:
            self._content_chunks.append(text)
        else:
            self._body_chunks.append(text)

    def _capture_meta(self, attr: dict[str, str]) -> None:
        name = (attr.get("name") or attr.get("property") or "").lower()
        content = attr.get("content", "").strip()
        if not name or not content:
            return
        if name in {
            "description",
            "og:description",
            "twitter:description",
            "og:title",
            "twitter:title",
        }:
            self._meta[name] = content

    def assembled(self) -> str:
        title = (
            self._meta.get("og:title")
            or self._meta.get("twitter:title")
            or " ".join(self._title_chunks).strip()
        )
        description = (
            self._meta.get("og:description")
            or self._meta.get("twitter:description")
            or self._meta.get("description")
            or ""
        )
        body_src = self._content_chunks if len(" ".join(self._content_chunks)) >= 80 else self._body_chunks
        body = re.sub(r"\s+", " ", " ".join(body_src)).strip()

        parts: list[str] = []
        if title:
            parts.append(f"Titel: {title}")
        if description:
            parts.append(f"Beskrivning: {description}")
        if body:
            parts.append(body)
        return "\n\n".join(parts).strip()[:8000]


def extract_text_from_html(html: str) -> str:
    parser = _TextExtractor()
    # Ignore malformed markup noise — feed what we can.
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — best-effort scrape
        pass
    return parser.assembled()


def source_domain(url: str) -> str:
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return (parsed.hostname or "").removeprefix("www.")
    except Exception:  # noqa: BLE001 — best-effort domain for display
        return ""


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    if not re.match(r"^https?://", url, re.I):
        return f"https://{url}"
    return url


async def fetch_url_text(url: str) -> str:
    normalized = normalize_url(url)
    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            response = await client.get(normalized, headers=headers)
    except httpx.TimeoutException as exc:
        raise ValueError("Hämtningen tog för lång tid — försök igen eller klistra in texten manuellt") from exc
    except httpx.RequestError as exc:
        raise ValueError(f"Kunde inte nå länken: {exc}") from exc

    if response.status_code >= 400:
        raise ValueError(
            f"Länken svarade med HTTP {response.status_code} "
            f"({source_domain(normalized) or 'okänd källa'})"
        )

    content_type = response.headers.get("content-type", "")
    body = response.text
    if "html" in content_type or body.lstrip().startswith("<!"):
        text = extract_text_from_html(body)
    elif body.lstrip().startswith("<"):
        text = extract_text_from_html(body)
    else:
        text = re.sub(r"\s+", " ", body).strip()[:8000]

    if len(text) < 40:
        raise ValueError(
            "Kunde inte läsa ut tillräckligt med innehåll från länken "
            "(sidan kan vara låst eller kräva JavaScript). Klistra in texten manuellt."
        )
    return text


def _type_label(message_type: MessageType) -> str:
    return "partipost / socialt inlägg" if message_type == "post" else "nyhetspost"


async def summarize_url_content(
    url: str,
    message_type: MessageType = "news",
    *,
    prompts: dict[str, str],
) -> str:
    page_text = await fetch_url_text(url)
    messages = [
        {
            "role": "system",
            "content": render_prompt(prompts, "messages.summarize_url.system"),
        },
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "messages.summarize_url.user",
                type_label=_type_label(message_type),
                page_text=page_text,
            ),
        },
    ]
    return await complete_text(messages)


def _variant_prompt(
    body: GenerateVariantsRequest,
    angle_instruction: str,
    source_material: str,
    *,
    prompts: dict[str, str],
) -> list[dict[str, str]]:
    context_bits = []
    if body.audience.strip():
        context_bits.append(f"Målgrupp: {body.audience.strip()}")
    if body.purpose.strip():
        context_bits.append(f"Syfte: {body.purpose.strip()}")
    if body.tone.strip():
        context_bits.append(f"Tonläge: {body.tone.strip()}")
    if body.source_url:
        context_bits.append(f"Källa: {normalize_url(body.source_url)}")
    context_block = "\n".join(context_bits) if context_bits else "Ingen extra kontext."

    return [
        {
            "role": "system",
            "content": render_prompt(prompts, "messages.variant.system"),
        },
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "messages.variant.user",
                type_label=_type_label(body.type),
                angle_instruction=angle_instruction,
                context_block=context_block,
                source_material=source_material,
            ),
        },
    ]


async def generate_message_variants(
    body: GenerateVariantsRequest,
    *,
    prompts: dict[str, str],
) -> list[MessageVariantOut]:
    source_material = body.raw_text
    if not source_material and body.source_url:
        source_material = await summarize_url_content(
            body.source_url, body.type, prompts=prompts
        )
    if not source_material:
        raise ValueError("Saknar underlag för generering")

    async def one(key: MessageVariant, label: str, prompt_key: str) -> MessageVariantOut:
        instruction = render_prompt(prompts, prompt_key)
        text = await complete_text(
            _variant_prompt(body, instruction, source_material, prompts=prompts)
        )
        return MessageVariantOut(key=key, label=label, body=text)

    results = await asyncio.gather(
        *[one(key, label, prompt_key) for key, label, prompt_key in VARIANT_KEYS]
    )
    return list(results)
