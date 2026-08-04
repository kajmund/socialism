"""Topic packs + tone classification via LLM (no keyword/heuristic fallback)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.llm import complete_structured
from app.services.report.bundles import RunBundle

TONE_LABELS: tuple[str, ...] = (
    "Kritisk / uppgiven",
    "Konstruktiv",
    "Positiv / hoppfull",
    "Neutral / oklassad",
)

ToneMode = Literal["llm"]

# Keep batches small — large structured prompts stall on DeepSeek.
_CLASSIFY_BATCH_SIZE = 8
_TEXT_CHARS = 200
# Cap LLM calls: sample highest-engagement texts (likes).
_MAX_CLASSIFY_TEXTS = 16


@dataclass
class TopicPack:
    label: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class BundleClassification:
    topic_packs: list[TopicPack] = field(default_factory=list)
    topic_shares: dict[str, float] = field(default_factory=dict)
    tone_shares: dict[str, float] = field(default_factory=dict)
    tone_mode: ToneMode = "llm"


class _TopicPackModel(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    keywords: list[str] = Field(default_factory=list, max_length=16)


class _TopicPacksResponse(BaseModel):
    topics: list[_TopicPackModel] = Field(min_length=1, max_length=4)


class _TopicItem(BaseModel):
    index: int
    topic: str


class _TopicBatchResponse(BaseModel):
    items: list[_TopicItem]


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


def _item_likes(item: dict) -> int:
    for key in ("num_likes", "likes", "like_count"):
        v = item.get(key)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _texts_for_classify(bundle: RunBundle, *, limit: int = _MAX_CLASSIFY_TEXTS) -> list[str]:
    """Prefer higher-engagement posts/comments; cap count for LLM cost/latency."""
    scored: list[tuple[int, str]] = []
    for p in bundle.posts:
        c = p.get("content") or p.get("text") or ""
        if c:
            scored.append((_item_likes(p), str(c)))
    for c in bundle.comments:
        t = c.get("content") or c.get("text") or ""
        if t:
            scored.append((_item_likes(c), str(t)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:limit]]


def _share_counts(labels: list[str], allowed: list[str]) -> dict[str, float]:
    counts: Counter[str] = Counter({lab: 0 for lab in allowed})
    for lab in labels:
        counts[lab if lab in counts else allowed[-1]] += 1
    total = sum(counts.values()) or 1
    return {lab: counts[lab] / total for lab in allowed}


async def derive_topic_packs(injection_texts: list[str]) -> list[TopicPack]:
    if not injection_texts:
        return []

    blob = "\n---\n".join(t[:800] for t in injection_texts[:8])
    result = await complete_structured(
        [
            {
                "role": "system",
                "content": (
                    "Du härleder ämnesetiketter för en svensk politisk debattsimulering. "
                    "Returnera 2–4 ämnen med korta svenska etiketter som fångar "
                    "injektionernas innehåll. Undvik generiska partinamn ensamma. "
                    "keywords är valfria hjälpord (behövs inte för klassning)."
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
        if t.label.strip()
    ]
    if not packs:
        raise RuntimeError("LLM returned no topic packs for injections")
    return packs


async def classify_topics(
    texts: list[str],
    packs: list[TopicPack],
    *,
    batch_size: int = _CLASSIFY_BATCH_SIZE,
) -> dict[str, float]:
    allowed = [p.label for p in packs] + ["Övrigt"]
    if not texts:
        return {lab: 0.0 for lab in allowed}
    if not packs:
        return {"Övrigt": 1.0}

    allowed_set = set(allowed)
    labels: list[str] = [""] * len(texts)
    pack_list = ", ".join(f"'{p.label}'" for p in packs)

    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        numbered = "\n".join(f"{i}. {t[:_TEXT_CHARS]}" for i, t in enumerate(chunk))
        result = await complete_structured(
            [
                {
                    "role": "system",
                    "content": (
                        "Klassificera varje svensk kommentar/inlägg efter ämne. "
                        f"Tillåtna värden: {pack_list}, eller 'Övrigt'. "
                        "Välj efter mening och kontext — inte enbart nyckelord. "
                        "Sarkasm och omskrivningar räknas till det ämne de egentligen handlar om. "
                        "Returnera index 0..n-1 för batchen."
                    ),
                },
                {"role": "user", "content": numbered},
            ],
            _TopicBatchResponse,
        )
        by_idx = {item.index: item.topic for item in result.items}
        for i in range(len(chunk)):
            raw = by_idx.get(i, "Övrigt")
            labels[start + i] = raw if raw in allowed_set else "Övrigt"
    return _share_counts(labels, allowed)


async def classify_tones(
    texts: list[str],
    *,
    batch_size: int = _CLASSIFY_BATCH_SIZE,
) -> tuple[dict[str, float], ToneMode]:
    if not texts:
        return {lab: 0.0 for lab in TONE_LABELS}, "llm"

    labels: list[str] = [""] * len(texts)
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        numbered = "\n".join(f"{i}. {t[:_TEXT_CHARS]}" for i, t in enumerate(chunk))
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
    return _share_counts(labels, list(TONE_LABELS)), "llm"


async def classify_bundle(bundle: RunBundle) -> BundleClassification:
    texts = _texts_for_classify(bundle)
    packs = await derive_topic_packs(bundle.injection_texts)
    topic_shares = await classify_topics(texts, packs)
    tone_shares, tone_mode = await classify_tones(texts)
    return BundleClassification(
        topic_packs=packs,
        topic_shares=topic_shares,
        tone_shares=tone_shares,
        tone_mode=tone_mode,
    )


async def classify_bundles(bundles: list[RunBundle]) -> list[BundleClassification]:
    return [await classify_bundle(b) for b in bundles]


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
