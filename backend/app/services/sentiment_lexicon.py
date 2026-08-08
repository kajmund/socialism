"""Swedish keyword sentiment (lexicon) shared by measurements and playground."""

from __future__ import annotations

import re
from typing import Literal

LexiconLabel = Literal["positive", "neutral", "negative"]

POS = {
    "bra",
    "bättre",
    "positiv",
    "glädje",
    "stödjer",
    "håller",
    "viktigt",
    "tack",
    "hopp",
    "stark",
    "rätt",
    "bra!",
}
NEG = {
    "dåligt",
    "sämre",
    "negativ",
    "arg",
    "sorgligt",
    "fel",
    "skandal",
    "rasar",
    "uselt",
    "hatar",
    "stopp",
    "nej",
}
STOP = {
    "och",
    "att",
    "det",
    "som",
    "en",
    "ett",
    "på",
    "är",
    "av",
    "för",
    "med",
    "till",
    "den",
    "de",
    "i",
    "om",
    "har",
    "inte",
    "jag",
    "vi",
    "du",
    "ni",
    "han",
    "hon",
    "eller",
    "men",
    "så",
    "var",
    "när",
    "från",
    "ska",
    "kan",
    "man",
    "sig",
    "the",
    "a",
    "an",
}


def tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[A-Za-zÅÄÖåäö]{3,}", (text or "").casefold())
        if t not in STOP
    ]


def classify_text(text: str) -> LexiconLabel:
    toks = set(tokens(text))
    p = len(toks & POS)
    n = len(toks & NEG)
    if p > n:
        return "positive"
    if n > p:
        return "negative"
    return "neutral"


def sentiment_shares(texts: list[str]) -> dict[str, float]:
    pos = neg = neu = 0
    for text in texts:
        label = classify_text(text)
        if label == "positive":
            pos += 1
        elif label == "negative":
            neg += 1
        else:
            neu += 1
    total = max(pos + neg + neu, 1)
    return {
        "positive": round(pos / total, 3),
        "neutral": round(neu / total, 3),
        "negative": round(neg / total, 3),
    }
