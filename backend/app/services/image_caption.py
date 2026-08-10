"""Shared vision caption prompts for image cache and playground."""

from __future__ import annotations

from typing import Literal

Locale = Literal["sv", "en"]


def rich_caption_prompt(locale: Locale) -> str:
    if locale == "en":
        return (
            "Describe this image in English for political communication analysis "
            "(roughly 4–8 sentences). Include:\n"
            "- Any visible text verbatim\n"
            "- People, symbols, colors, composition, and mood\n"
            "- What might be ambiguous or open to interpretation\n"
            "Stay descriptive and neutral — do not judge or advise."
        )
    return (
        "Beskriv bilden på svenska för politisk kommunikationsanalys "
        "(ca 4–8 meningar). Ta med:\n"
        "- Synlig text ordagrant\n"
        "- Personer, symboler, färger, komposition och stämning\n"
        "- Vad som kan vara tvetydigt eller tolkningsbart\n"
        "Håll dig beskrivande och neutral — värdera eller rådge inte."
    )
