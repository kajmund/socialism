"""Playground helpers: SSR calibration, lexicon compare, prompt side-by-side."""

from __future__ import annotations

from typing import Literal

from app.services.sentiment_lexicon import LexiconLabel, classify_text, sentiment_shares
from app.services.ssr import AnchorSet, rate_texts, style_anchors, tone_anchors

Dimension = Literal["tone", "style"]
ThreeWay = LexiconLabel


def default_anchor_set(*, dimension: Dimension, locale: str) -> AnchorSet:
    if dimension == "tone":
        return tone_anchors(locale=locale)
    return style_anchors(locale=locale)


def resolve_anchor_set(
    *,
    dimension: Dimension,
    locale: str,
    labels: list[str] | None,
    statements: list[str] | None,
) -> AnchorSet:
    if labels is None and statements is None:
        return default_anchor_set(dimension=dimension, locale=locale)
    if labels is None or statements is None:
        raise ValueError("labels and statements must both be set when overriding anchors")
    if len(labels) != len(statements):
        raise ValueError(
            f"labels ({len(labels)}) and statements ({len(statements)}) length mismatch"
        )
    if not labels:
        raise ValueError("labels and statements must be non-empty")
    base = default_anchor_set(dimension=dimension, locale=locale)
    return AnchorSet(
        name=f"{base.name}_playground",
        version="playground",
        labels=tuple(labels),
        statements=tuple(statements),
    )


def argmax_label(pmf: dict[str, float]) -> str:
    if not pmf:
        return ""
    return max(pmf.items(), key=lambda item: item[1])[0]


def tone_label_to_bucket(label: str, labels: tuple[str, ...]) -> ThreeWay:
    """Map 5-level tone argmax onto positive/neutral/negative via label index."""
    try:
        idx = labels.index(label)
    except ValueError:
        return "neutral"
    n = len(labels)
    if n == 0:
        return "neutral"
    mid = n // 2
    if idx < mid:
        return "negative"
    if idx > mid:
        return "positive"
    return "neutral"


def confusion_counts(
    predicted: list[str],
    actual: list[str],
) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {}
    for pred, act in zip(predicted, actual, strict=True):
        row = matrix.setdefault(act, {})
        row[pred] = row.get(pred, 0) + 1
    return matrix


async def rate_case(
    texts: list[str],
    *,
    dimension: Dimension,
    locale: str,
    labels: list[str] | None,
    statements: list[str] | None,
    temperature: float,
    human_labels: list[str] | None,
) -> dict:
    anchor_set = resolve_anchor_set(
        dimension=dimension,
        locale=locale,
        labels=labels,
        statements=statements,
    )
    if human_labels is not None and len(human_labels) != len(texts):
        raise ValueError("human_labels must match texts length")

    result = await rate_texts(texts, anchor_set, temperature=temperature)
    predicted = [argmax_label(pmf) for pmf in result.per_text_pmfs]
    per_text = [
        {"text": text, "pmf": pmf, "predicted_label": pred}
        for text, pmf, pred in zip(texts, result.per_text_pmfs, predicted, strict=True)
    ]

    out: dict = {
        "anchor_set_name": result.anchor_set_name,
        "anchor_set_version": result.anchor_set_version,
        "labels": list(result.labels),
        "shares": result.shares,
        "per_text": per_text,
    }
    if human_labels is not None:
        hits = sum(1 for p, h in zip(predicted, human_labels, strict=True) if p == h)
        total = max(len(texts), 1)
        out["human_labels"] = human_labels
        out["accuracy"] = round(hits / total, 4)
        out["confusion"] = confusion_counts(predicted, human_labels)
    return out


async def compare_ssr_lexicon(
    texts: list[str],
    *,
    locale: str,
    labels: list[str] | None,
    statements: list[str] | None,
    temperature: float,
) -> dict:
    anchor_set = resolve_anchor_set(
        dimension="tone",
        locale=locale,
        labels=labels,
        statements=statements,
    )
    result = await rate_texts(texts, anchor_set, temperature=temperature)
    rows = []
    matches = 0
    for text, pmf in zip(texts, result.per_text_pmfs, strict=True):
        ssr_label = argmax_label(pmf)
        ssr_bucket = tone_label_to_bucket(ssr_label, result.labels)
        lex_label = classify_text(text)
        match = ssr_bucket == lex_label
        if match:
            matches += 1
        rows.append(
            {
                "text": text,
                "ssr_label": ssr_label,
                "ssr_bucket": ssr_bucket,
                "lexicon_label": lex_label,
                "match": match,
                "pmf": pmf,
            }
        )
    total = max(len(texts), 1)
    return {
        "anchor_set_name": result.anchor_set_name,
        "anchor_set_version": result.anchor_set_version,
        "labels": list(result.labels),
        "ssr_shares": result.shares,
        "lexicon_shares": sentiment_shares(texts),
        "agreement_rate": round(matches / total, 4) if texts else 0.0,
        "rows": rows,
    }
