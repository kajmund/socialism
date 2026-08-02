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

VARIANT_SPECS: list[tuple[MessageVariant, str, str]] = [
    (
        "analytical",
        "Professionell / analytisk",
        "Skriv med en professionell, analytisk vinkel. Tydliga argument, saklig ton.",
    ),
    (
        "narrative",
        "Personlig / berättande",
        "Skriv med en personlig, berättande vinkel. Mänsklig röst, konkret vardag.",
    ),
    (
        "concise",
        "Kort / koncis",
        "Skriv kort och koncist. Max 2–3 meningar, hög densitet, ingen fluff.",
    ),
]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            text = data.strip()
            if text:
                self._chunks.append(text)

    def text(self) -> str:
        return " ".join(self._chunks)


def extract_text_from_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = re.sub(r"\s+", " ", parser.text()).strip()
    return text[:8000]


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
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        response = await client.get(
            normalized,
            headers={"User-Agent": "Opinionssimulator/0.1 (+budskapsverkstad)"},
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        body = response.text
        if "html" in content_type or body.lstrip().startswith("<"):
            return extract_text_from_html(body)
        return re.sub(r"\s+", " ", body).strip()[:8000]


def _type_label(message_type: MessageType) -> str:
    return "partipost / socialt inlägg" if message_type == "post" else "nyhetspost"


async def summarize_url_content(url: str, message_type: MessageType = "news") -> str:
    page_text = await fetch_url_text(url)
    if not page_text:
        raise ValueError("Kunde inte hämta något läsbart innehåll från länken")
    messages = [
        {
            "role": "system",
            "content": (
                "Du sammanfattar webbinnehåll på svenska för politisk budskapsutveckling. "
                "Returnera endast sammanfattningen, ingen meta-kommentar."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Sammanfatta följande innehåll kort (5–8 meningar) som underlag för en "
                f"{_type_label(message_type)}:\n\n{page_text}"
            ),
        },
    ]
    return await complete_text(messages)


def _variant_prompt(
    body: GenerateVariantsRequest,
    angle_instruction: str,
    source_material: str,
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
            "content": (
                "Du skriver politiska budskap på svenska för Opinionssimulator. "
                "Returnera endast budskapstexten, ingen rubrik eller meta-kommentar."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Skriv en {_type_label(body.type)}.\n"
                f"{angle_instruction}\n\n"
                f"Kontext:\n{context_block}\n\n"
                f"Underlag:\n{source_material}"
            ),
        },
    ]


async def generate_message_variants(
    body: GenerateVariantsRequest,
) -> list[MessageVariantOut]:
    source_material = body.raw_text
    if not source_material and body.source_url:
        source_material = await summarize_url_content(body.source_url, body.type)
    if not source_material:
        raise ValueError("Saknar underlag för generering")

    async def one(key: MessageVariant, label: str, instruction: str) -> MessageVariantOut:
        text = await complete_text(_variant_prompt(body, instruction, source_material))
        return MessageVariantOut(key=key, label=label, body=text)

    results = await asyncio.gather(
        *[one(key, label, instruction) for key, label, instruction in VARIANT_SPECS]
    )
    return list(results)
