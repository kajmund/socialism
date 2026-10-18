"""Prompt and JSON parse for the Cerebras reranker. No invented IDs."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.retrieval.search import SearchHit

MATCH = "MATCH"
NO_MATCH = "NO_MATCH"
UNCERTAIN = "UNCERTAIN"
LABELS = frozenset({MATCH, NO_MATCH, UNCERTAIN})
TASK = "formulation_presence"
REASONED = "reasoned"
MINIMAL = "minimal"


@dataclass(frozen=True)
class Candidate:
    short_id: str
    key: str
    relative_path: str
    rank: int
    text: str


@dataclass(frozen=True)
class ParsedJudgment:
    short_id: str
    key: str
    label: str
    reason: str


def short_id_for(index: int) -> str:
    return f"c{index:02d}"


def candidates_from_hits(hits: list[SearchHit]) -> list[Candidate]:
    return [
        Candidate(
            short_id=short_id_for(index),
            key=hit.key,
            relative_path=hit.relative_path,
            rank=hit.rank,
            text=hit.text,
        )
        for index, hit in enumerate(hits, start=1)
    ]


def build_messages(
    query: str,
    candidates: list[Candidate],
    *,
    variant: str = REASONED,
) -> list[dict[str, str]]:
    blocks = []
    for item in candidates:
        blocks.append(f"{item.short_id}\n{item.text.strip()}")
    if variant == MINIMAL:
        instruction = (
            "Returnera JSON med bara id:n som är MATCH eller UNCERTAIN. "
            "Alla övriga id:n är NO_MATCH. Ingen motivering.\n"
            '{"match":["c01"],"uncertain":["c02"]}'
        )
    else:
        instruction = (
            "Returnera JSON med exakt ett omdöme per id:\n"
            '{"judgments":[{"id":"c01","label":"MATCH|NO_MATCH|UNCERTAIN","reason":"..."}]}'
        )
    user = (
        "Uppgiften är formulering, inte gällande avtalsvillkor. "
        "Bedöm om klausulen innehåller en relevant formulering för frågan. "
        "MATCH = relevant formulering finns. "
        "NO_MATCH = den finns inte. "
        "UNCERTAIN = du kan inte avgöra. "
        "Hitta inte på klausuler, citat eller id:n.\n\n"
        f"Fråga: {query}\n\n"
        "Klausuler:\n\n"
        + "\n\n".join(blocks)
        + "\n\n"
        + instruction
    )
    return [
        {
            "role": "system",
            "content": (
                "Du väljer vilka klausuler som innehåller en relevant formulering. "
                "Du är inte en juridisk bevismotor. Svara bara med JSON."
            ),
        },
        {"role": "user", "content": user},
    ]


def parse_judgments(payload: dict[str, object], candidates: list[Candidate]) -> list[ParsedJudgment]:
    allowed = {item.short_id: item for item in candidates}
    raw = payload.get("judgments")
    if not isinstance(raw, list) or not raw:
        raise ValueError("Cerebras response is missing judgments")
    seen: set[str] = set()
    parsed: list[ParsedJudgment] = []
    invented: list[str] = []
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("Cerebras judgment is not an object")
        short_id = str(row.get("id") or "")
        label = str(row.get("label") or "").upper()
        if short_id not in allowed:
            invented.append(short_id)
            continue
        if label not in LABELS:
            raise ValueError(f"Cerebras label is not allowed: {label}")
        if short_id in seen:
            raise ValueError(f"Cerebras returned duplicate id {short_id}")
        seen.add(short_id)
        item = allowed[short_id]
        parsed.append(
            ParsedJudgment(
                short_id=short_id,
                key=item.key,
                label=label,
                reason=str(row.get("reason") or ""),
            )
        )
    if invented:
        raise ValueError(f"Cerebras invented ids: {sorted(invented)}")
    missing = sorted(set(allowed) - seen)
    if missing:
        raise ValueError(f"Cerebras omitted ids: {missing}")
    return parsed


def parse_minimal(
    payload: dict[str, object], candidates: list[Candidate]
) -> tuple[list[ParsedJudgment], dict[str, list[str]]]:
    allowed = {item.short_id: item for item in candidates}
    match_ids = _id_list(payload.get("match"), "match")
    uncertain_ids = _id_list(payload.get("uncertain"), "uncertain")
    invented: list[str] = []
    duplicates: list[str] = []
    labels: dict[str, str] = {}
    for short_id in match_ids:
        if short_id not in allowed:
            invented.append(short_id)
            continue
        if short_id in labels:
            duplicates.append(short_id)
            continue
        labels[short_id] = MATCH
    for short_id in uncertain_ids:
        if short_id not in allowed:
            invented.append(short_id)
            continue
        if short_id in labels:
            duplicates.append(short_id)
            continue
        labels[short_id] = UNCERTAIN
    parsed = [
        ParsedJudgment(
            short_id=item.short_id,
            key=item.key,
            label=labels.get(item.short_id, NO_MATCH),
            reason="",
        )
        for item in candidates
    ]
    return parsed, {"invented": invented, "duplicates": duplicates}


def _id_list(raw: object, field: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"Cerebras {field} is not a list")
    return [str(item) for item in raw]
