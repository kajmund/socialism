"""Topic packs from injections + tone classification (LLM with heuristic fallback)."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.config import settings
from app.llm import complete_structured
from app.services.report.bundles import RunBundle

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-zåäöA-ZÅÄÖ0-9%]+")

_STOPWORDS: frozenset[str] = frozenset(
    {
        "och",
        "att",
        "det",
        "som",
        "för",
        "med",
        "på",
        "av",
        "en",
        "ett",
        "den",
        "de",
        "är",
        "till",
        "inte",
        "om",
        "har",
        "ska",
        "kan",
        "vi",
        "ni",
        "jag",
        "man",
        "var",
        "vad",
        "när",
        "eller",
        "från",
        "utan",
        "också",
        "vara",
        "bli",
        "blir",
        "över",
        "under",
        "efter",
        "innan",
        "denna",
        "detta",
        "dessa",
        "alla",
        "mer",
        "mycket",
        "hela",
        "sverige",
        "socialdemokraterna",
        "äldre",
        "barn",
        "unga",
        "folk",
        "viktig",
        "avgörande",
        "stoppa",
        "vill",
        "http",
        "https",
        "www",
    }
)

TONE_CRITICAL = ("kritisk", "uselt", "dåligt", "misslyck", "skandal", "strunt", "skärp", "valfläsk")
TONE_CONSTRUCTIVE = ("borde", "förslag", "lösning", "kan vi", "bättre om", "konkret")
TONE_POSITIVE = ("bra", "hopp", "positiv", "framåt", "glad", "tack")

TONE_LABELS: tuple[str, ...] = (
    "Kritisk / uppgiven",
    "Konstruktiv",
    "Positiv / hoppfull",
    "Neutral / oklassad",
)

ToneMode = Literal["llm", "heuristic"]


@dataclass
class TopicPack:
    label: str
    keywords: list[str]


@dataclass
class BundleClassification:
    topic_packs: list[TopicPack] = field(default_factory=list)
    topic_shares: dict[str, float] = field(default_factory=dict)
    tone_shares: dict[str, float] = field(default_factory=dict)
    tone_mode: ToneMode = "heuristic"


class _TopicPackModel(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    keywords: list[str] = Field(min_length=1, max_length=16)


class _TopicPacksResponse(BaseModel):
    topics: list[_TopicPackModel] = Field(min_length=1, max_length=4)


class _ToneItem(BaseModel):
    index: int
    tone: Literal[
        "Kritisk / uppgiven",
        "Konstruktiv",
        "Positiv / hoppfull",
        "Neutral / oklassad",
    ]


class _ToneBatchResponse(BaseModel):
    items: list[_ToneItem]


def _texts(bundle: RunBundle) -> list[str]:
    out: list[str] = []
    for p in bundle.posts:
        c = p.get("content") or p.get("text") or ""
        if c:
            out.append(str(c))
    for c in bundle.comments:
        t = c.get("content") or c.get("text") or ""
        if t:
            out.append(str(t))
    return out


def fallback_topic_packs(injection_texts: list[str]) -> list[TopicPack]:
    counts: Counter[str] = Counter()
    for text in injection_texts:
        for w in _WORD_RE.findall(text.lower()):
            if len(w) >= 4 and w not in _STOPWORDS:
                counts[w] += 1
    keywords = [w for w, _ in counts.most_common(12)]
    if not keywords:
        return []
    return [TopicPack(label="Budskap", keywords=keywords)]


async def derive_topic_packs(
    injection_texts: list[str],
    *,
    use_llm: bool,
) -> list[TopicPack]:
    if not injection_texts:
        return []
    if not use_llm:
        return fallback_topic_packs(injection_texts)

    blob = "\n---\n".join(t[:800] for t in injection_texts[:8])
    try:
        result = await complete_structured(
            [
                {
                    "role": "system",
                    "content": (
                        "Du härleder ämnesetiketter för en svensk politisk debattsimulering. "
                        "Returnera 2–4 ämnen med svenska nyckelord (lowercase substring) "
                        "som fångar injektionernas innehåll. Undvik generiska partinamn ensamma."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Injektionstexter:\n{blob}",
                },
            ],
            _TopicPacksResponse,
        )
        packs = [
            TopicPack(
                label=t.label.strip(),
                keywords=[k.strip().lower() for k in t.keywords if k.strip()],
            )
            for t in result.topics
            if t.label.strip() and any(k.strip() for k in t.keywords)
        ]
        return packs or fallback_topic_packs(injection_texts)
    except Exception:
        logger.exception("derive_topic_packs LLM failed; using fallback")
        return fallback_topic_packs(injection_texts)


def classify_topics(texts: list[str], packs: list[TopicPack]) -> dict[str, float]:
    labels = [p.label for p in packs] + ["Övrigt"]
    counts: Counter[str] = Counter({lab: 0 for lab in labels})
    if not texts:
        return {lab: 0.0 for lab in labels}

    for text in texts:
        low = text.lower()
        best: tuple[int, str] | None = None
        for pack in packs:
            for kw in pack.keywords:
                if kw and kw in low:
                    cand = (len(kw), pack.label)
                    if best is None or cand[0] > best[0]:
                        best = cand
        counts[best[1] if best else "Övrigt"] += 1

    total = sum(counts.values()) or 1
    return {lab: counts[lab] / total for lab in labels}


def tone_shares_heuristic(texts: list[str]) -> dict[str, float]:
    counts = Counter({lab: 0 for lab in TONE_LABELS})
    for text in texts:
        low = text.lower()
        if any(w in low for w in TONE_CRITICAL):
            counts["Kritisk / uppgiven"] += 1
        elif any(w in low for w in TONE_CONSTRUCTIVE):
            counts["Konstruktiv"] += 1
        elif any(w in low for w in TONE_POSITIVE):
            counts["Positiv / hoppfull"] += 1
        else:
            counts["Neutral / oklassad"] += 1
    total = sum(counts.values()) or 1
    return {lab: counts[lab] / total for lab in TONE_LABELS}


async def classify_tones(
    texts: list[str],
    *,
    use_llm: bool,
    batch_size: int = 20,
) -> tuple[dict[str, float], ToneMode]:
    if not texts:
        return {lab: 0.0 for lab in TONE_LABELS}, "heuristic"
    if not use_llm:
        return tone_shares_heuristic(texts), "heuristic"

    labels: list[str] = [""] * len(texts)
    try:
        for start in range(0, len(texts), batch_size):
            chunk = texts[start : start + batch_size]
            numbered = "\n".join(f"{i}. {t[:350]}" for i, t in enumerate(chunk))
            result = await complete_structured(
                [
                    {
                        "role": "system",
                        "content": (
                            "Klassificera varje svensk kommentar/inlägg efter ton. "
                            "Tillåtna värden: "
                            "'Kritisk / uppgiven', 'Konstruktiv', "
                            "'Positiv / hoppfull', 'Neutral / oklassad'. "
                            "Sarkasm, valfläsk-misstro och skarp kritik = Kritisk / uppgiven. "
                            "Returnera index 0..n-1 för batchen."
                        ),
                    },
                    {"role": "user", "content": numbered},
                ],
                _ToneBatchResponse,
            )
            by_idx = {item.index: item.tone for item in result.items}
            for i in range(len(chunk)):
                labels[start + i] = by_idx.get(i, "Neutral / oklassad")
        counts = Counter({lab: 0 for lab in TONE_LABELS})
        for lab in labels:
            counts[lab if lab in counts else "Neutral / oklassad"] += 1
        total = sum(counts.values()) or 1
        return {lab: counts[lab] / total for lab in TONE_LABELS}, "llm"
    except Exception:
        logger.exception("classify_tones LLM failed; using heuristic")
        return tone_shares_heuristic(texts), "heuristic"


async def classify_bundle(
    bundle: RunBundle,
    *,
    use_llm: bool | None = None,
) -> BundleClassification:
    llm = bool(settings.deepseek_api_key) if use_llm is None else use_llm
    texts = _texts(bundle)
    packs = await derive_topic_packs(bundle.injection_texts, use_llm=llm)
    topic_shares = classify_topics(texts, packs)
    tone_shares, tone_mode = await classify_tones(texts, use_llm=llm)
    return BundleClassification(
        topic_packs=packs,
        topic_shares=topic_shares,
        tone_shares=tone_shares,
        tone_mode=tone_mode,
    )


async def classify_bundles(
    bundles: list[RunBundle],
    *,
    use_llm: bool | None = None,
) -> list[BundleClassification]:
    return [await classify_bundle(b, use_llm=use_llm) for b in bundles]


def meta_topics_line(classifications: list[BundleClassification]) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for c in classifications:
        for pack in c.topic_packs:
            if pack.label not in seen:
                seen.add(pack.label)
                labels.append(pack.label)
        if "Övrigt" in c.topic_shares and c.topic_shares.get("Övrigt", 0) > 0:
            if "Övrigt" not in seen:
                seen.add("Övrigt")
                labels.append("Övrigt")
    return "; ".join(labels) if labels else "Se ämnesfördelning i rapporten"
