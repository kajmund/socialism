"""Match panel experts when speech-to-text respells their names."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-zÅÄÖåäöÆØæøÉé]+")
_LETTERS = str.maketrans(
    {
        "å": "a",
        "ä": "a",
        "ö": "o",
        "æ": "a",
        "ø": "o",
        "é": "e",
        "è": "e",
    }
)


def name_key(value: str) -> str:
    """Fold Swedish spellings that speech-to-text swaps, such as Klas and Claes."""
    text = value.lower().translate(_LETTERS)
    text = text.replace("ae", "a").replace("ch", "k").replace("ck", "k")
    text = text.replace("th", "t").replace("ph", "f")
    chars: list[str] = []
    for index, char in enumerate(text):
        if char == "c":
            nxt = text[index + 1] if index + 1 < len(text) else ""
            chars.append("s" if nxt in "eiy" else "k")
        elif char == "z":
            chars.append("s")
        elif char == "w":
            chars.append("v")
        elif char == "h" and chars and chars[-1] not in "aeiou":
            continue
        elif char.isalpha():
            chars.append(char)
    if chars and chars[-1] == "h" and len(chars) > 3:
        chars.pop()
    return "".join(chars)


def name_bias_prompt(names: list[str]) -> str:
    cleaned = [name.strip() for name in names if name.strip()]
    if not cleaned:
        return ""
    return "Stava dessa personnamn exakt när de nämns: " + ", ".join(cleaned) + "."


def addressed_member(utterance: str, member_names: dict[str, str]) -> str | None:
    """Return the one expert a token names, in utterance order."""
    index = _name_index(member_names)
    for match in _TOKEN.finditer(utterance):
        hits = _hits(name_key(match.group(0)), index)
        if len(hits) == 1:
            return next(iter(hits))
    return None


def correct_names(utterance: str, member_names: dict[str, str]) -> str:
    """Rewrite a misheard name token to the expert's own spelling."""
    index = _name_index(member_names)

    def replace(match: re.Match[str]) -> str:
        hits = _hits(name_key(match.group(0)), index)
        if len(hits) != 1:
            return match.group(0)
        persona_id = next(iter(hits))
        return index[name_key(match.group(0))][persona_id]

    return _TOKEN.sub(replace, utterance)


def _name_index(member_names: dict[str, str]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for persona_id, name in member_names.items():
        for part in re.split(r"[\s-]+", name.strip()):
            key = name_key(part)
            if len(key) < 2:
                continue
            index.setdefault(key, {})[persona_id] = part
    return index


def _hits(key: str, index: dict[str, dict[str, str]]) -> dict[str, str]:
    if len(key) < 2:
        return {}
    return dict(index.get(key, {}))
