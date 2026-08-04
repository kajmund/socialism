"""Detect lexical convergence: shared verbatim phrases across population agents."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Literal

# Calibrate empirically — change here without touching call sites.
CONVERGENCE_AGENT_SHARE_THRESHOLD = 0.40
MIN_NGRAM_WORDS = 3
MAX_NGRAM_WORDS = 6
# Two-word anchors (e.g. "kollektivt döma") — both words must be content words.
ANCHOR_NGRAM_WORDS = 2

# Coarse Swedish suffix stripping — not full lemmatization; see _normalize_token().
_SV_SUFFIXES = (
    "ningarna",
    "ningen",
    "ningar",
    "ning",
    "ande",
    "ende",
    "arna",
    "orna",
    "erna",
    "ens",
    "ets",
    "en",
    "et",
    "na",
    "ne",
    "er",
    "ar",
    "or",
    "t",
    "a",
    "n",
    "s",
)
_MIN_STEM_LEN = 4
# Fallback when suffix rules miss: compare word prefixes (documented simplification).
_COARSE_PREFIX_LEN = 6

_SV_STOP = {
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

_WORD = re.compile(r"[\wåäöÅÄÖ']+", re.UNICODE)
WarningKind = Literal["source_phrase_echo", "cross_agent_convergence"]


def _words(text: str) -> list[str]:
    return [m.group(0) for m in _WORD.finditer(text or "")]


def _normalize_token(word: str) -> str:
    """Coarse Swedish normalization for phrase clustering (not full lemmatization).

    Applies lowercasing, common suffix stripping, then optional prefix fallback
    for long tokens — enough to merge case and inflection variants without
    collapsing unrelated words.
    """
    w = word.casefold()
    if len(w) <= 3:
        return w
    for suffix in _SV_SUFFIXES:
        if len(w) <= len(suffix):
            continue
        if w.endswith(suffix):
            stem = w[: -len(suffix)]
            if len(stem) >= _MIN_STEM_LEN:
                return stem
    if len(w) >= 8:
        return w[:_COARSE_PREFIX_LEN]
    return w


def _normalized_words(text: str) -> list[str]:
    return [_normalize_token(w) for w in _words(text)]


def _normalized_text(text: str) -> str:
    return " ".join(_normalized_words(text))


def _is_content_word(word: str) -> bool:
    return _normalize_token(word) not in _SV_STOP


def _content_word_count(words: list[str]) -> int:
    return sum(1 for w in words if w not in _SV_STOP)


def _anchor_bigrams(words: list[str]) -> set[str]:
    """Two-word anchors; both words must be content words (not stopwords)."""
    out: set[str] = set()
    if len(words) < ANCHOR_NGRAM_WORDS:
        return out
    for i in range(0, len(words) - ANCHOR_NGRAM_WORDS + 1):
        window = words[i : i + ANCHOR_NGRAM_WORDS]
        if all(w not in _SV_STOP for w in window):
            out.add(" ".join(window))
    return out


def _phrase_candidates(words: list[str]) -> set[str]:
    return _ngrams_from_words(words) | _anchor_bigrams(words)


def _phrase_candidates_from_text(text: str) -> set[str]:
    return _phrase_candidates(_normalized_words(text))


def _ngrams_from_words(
    words: list[str],
    *,
    min_words: int = MIN_NGRAM_WORDS,
    max_words: int = MAX_NGRAM_WORDS,
) -> set[str]:
    out: set[str] = set()
    n_words = len(words)
    for size in range(min_words, max_words + 1):
        if n_words < size:
            continue
        for i in range(0, n_words - size + 1):
            window = words[i : i + size]
            if _content_word_count(window) < 1:
                continue
            out.add(" ".join(window))
    return out


def _population_user_ids(agents: list[dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    for agent in agents:
        if agent.get("role") == "injector":
            continue
        idx = agent.get("index")
        if idx is None:
            continue
        ids.add(int(idx))
    return ids


def _user_id(row: dict[str, Any]) -> int:
    raw = row.get("user_id")
    if raw is None:
        return -1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def _agent_texts(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    population_ids: set[int],
) -> dict[int, str]:
    chunks: dict[int, list[str]] = defaultdict(list)
    for post in posts:
        uid = _user_id(post)
        if uid not in population_ids:
            continue
        quote = (post.get("quote_content") or "").strip()
        content = (post.get("content") or "").strip()
        text = f"{quote}\n{content}".strip()
        if text:
            chunks[uid].append(text)
    for comment in comments:
        uid = _user_id(comment)
        if uid not in population_ids:
            continue
        content = (comment.get("content") or "").strip()
        if content:
            chunks[uid].append(content)
    return {uid: "\n".join(parts) for uid, parts in chunks.items()}


def _agents_with_phrase(
    agent_texts: dict[int, str],
    phrase_key: str,
) -> set[int]:
    return {
        uid
        for uid, text in agent_texts.items()
        if phrase_key in _normalized_text(text)
    }


def _display_phrase(
    phrase_key: str,
    agent_texts: dict[int, str],
    users: set[int],
) -> str:
    """Pick the most common surface form among matching agents."""
    stems = phrase_key.split()
    n = len(stems)
    if n == 0:
        return phrase_key
    counts: Counter[str] = Counter()
    for uid in users:
        surface_words = _words(agent_texts[uid])
        norm = [_normalize_token(w) for w in surface_words]
        for i in range(0, len(norm) - n + 1):
            if norm[i : i + n] == stems:
                counts[" ".join(surface_words[i : i + n])] += 1
    if counts:
        return counts.most_common(1)[0][0]
    return phrase_key


def _phrase_warnings(
    phrases: set[str],
    *,
    agent_texts: dict[int, str],
    population_count: int,
    threshold: float,
    kind: WarningKind,
    source: str | None = None,
) -> list[dict[str, Any]]:
    if population_count <= 0:
        return []
    warnings: list[dict[str, Any]] = []
    for phrase_key in sorted(phrases, key=len, reverse=True):
        users = _agents_with_phrase(agent_texts, phrase_key)
        if len(users) < 2:
            continue
        share = len(users) / population_count
        if share < threshold:
            continue
        entry: dict[str, Any] = {
            "phrase_key": phrase_key,
            "phrase": _display_phrase(phrase_key, agent_texts, users),
            "agent_share": round(share, 3),
            "agent_count": len(users),
            "kind": kind,
        }
        if source:
            entry["source"] = source
        warnings.append(entry)
    warnings.sort(key=lambda w: (-w["agent_share"], len(w["phrase_key"])))
    return warnings


def _drop_subsumed_phrases(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer shorter anchor phrases over longer extensions at similar coverage."""
    kept: list[dict[str, Any]] = []
    for w in sorted(warnings, key=lambda x: (-x["agent_share"], len(x["phrase_key"]))):
        pc = w["phrase_key"]
        kind = w["kind"]
        source = w.get("source")
        kept = [
            k
            for k in kept
            if not (
                pc != k["phrase_key"]
                and pc in k["phrase_key"]
                and kind == k["kind"]
                and source == k.get("source")
            )
        ]
        if any(
            pc != k["phrase_key"]
            and k["phrase_key"] in pc
            and kind == k["kind"]
            and source == k.get("source")
            for k in kept
        ):
            continue
        kept.append(w)
    return kept


def _strip_phrase_keys(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in warnings:
        entry = {k: v for k, v in w.items() if k != "phrase_key"}
        out.append(entry)
    return out


def analyze_lexical_convergence(
    *,
    posts: list[dict[str, Any]] | None = None,
    comments: list[dict[str, Any]] | None = None,
    agents: list[dict[str, Any]] | None = None,
    injection_texts: list[tuple[str, str]] | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Flag shared phrase reuse across population agents.

    Phrases are clustered with coarse Swedish normalization (case + common
    suffix stripping) before counting — not exact verbatim string match.

    Returns a quality_warnings payload suitable for variant results.
    """
    posts = list(posts or [])
    comments = list(comments or [])
    agents = list(agents or [])
    injection_texts = list(injection_texts or [])
    cutoff = (
        CONVERGENCE_AGENT_SHARE_THRESHOLD
        if threshold is None
        else threshold
    )

    population_ids = _population_user_ids(agents)
    population_count = len(population_ids)
    agent_texts = _agent_texts(posts, comments, population_ids)

    warnings: list[dict[str, Any]] = []

    for source_label, source_text in injection_texts:
        source_phrases = _phrase_candidates_from_text(source_text)
        warnings.extend(
            _phrase_warnings(
                source_phrases,
                agent_texts=agent_texts,
                population_count=population_count,
                threshold=cutoff,
                kind="source_phrase_echo",
                source=source_label,
            )
        )

    all_phrase_counts: dict[str, set[int]] = defaultdict(set)
    for uid, text in agent_texts.items():
        for phrase_key in _phrase_candidates_from_text(text):
            all_phrase_counts[phrase_key].add(uid)

    cross_phrases = {
        phrase_key
        for phrase_key, users in all_phrase_counts.items()
        if len(users) >= 2 and len(users) / population_count >= cutoff
    }
    warnings.extend(
        _phrase_warnings(
            cross_phrases,
            agent_texts=agent_texts,
            population_count=population_count,
            threshold=cutoff,
            kind="cross_agent_convergence",
        )
    )

    seen: set[tuple[str, str | None]] = set()
    deduped: list[dict[str, Any]] = []
    for w in warnings:
        key = (w["phrase_key"], w.get("source"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(w)

    deduped = _drop_subsumed_phrases(deduped)

    return {
        "threshold": cutoff,
        "population_agents": population_count,
        "warnings": _strip_phrase_keys(deduped),
    }
