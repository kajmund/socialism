"""Human-facing lagen.nu titles and excerpts. No retrieval here."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[0-9A-Za-zÅÄÖåäö]+")
_HTML_TAG = re.compile(r"<[^>]+>")
_PROP_PATH = re.compile(
    r"/prop/(\d{4})(?:/(\d{2}))?:(\d+)(?:[#/?]|$)",
    re.IGNORECASE,
)
_SOU_PATH = re.compile(r"/sou/(\d{4}):(\d+)(?:[#/?]|$)", re.IGNORECASE)
_DS_PATH = re.compile(r"/ds/(\d{4}):(\d+)(?:[#/?]|$)", re.IGNORECASE)
_BET_PATH = re.compile(r"/bet/(\d{4}/\d{2}:[A-Za-z]+\d+)(?:[#/?]|$)", re.IGNORECASE)
_DIR_PATH = re.compile(r"/dir/(\d{4}):(\d+)(?:[#/?]|$)", re.IGNORECASE)
_SFS_PATH = re.compile(r"/(\d{4}):(\d+)(?:[#/?]|$)", re.IGNORECASE)
_NJA_PATH = re.compile(r"/dom/nja/(\d{4})s(\d+)(?:[#/?]|$)", re.IGNORECASE)
_TEXT_CITATION = re.compile(
    r"\b(?:Prop\.\s*\d{4}(?:/\d{2})?:\d+|SOU\s+\d{4}:\d+|Ds\s+\d{4}:\d+|"
    r"Bet\.\s*\d{4}/\d{2}:[A-Za-z]+\d+|NJA\s+\d{4}\s+s\.\s*\d+|SFS\s+\d{4}:\d+)\b",
    re.IGNORECASE,
)
_HEADER_NOISE = re.compile(
    r"regeringens\s+proposition(?:\s+nr\.?\s*\d+(?:\s+år\s+\d+)?)?|"
    r"prop\.\s*\d{4}(?:/\d{2})?:\d+|"
    r"sou\s+\d{4}:\d+|"
    r"statens\s+offentliga\s+utredningar|"
    r"\bnr\.?\s*\d+\b|"
    r"beslutad\s+den\s+\d{1,2}\s+\w+\s+\d{4}|"
    r"\bm\.m\.\b",
    re.IGNORECASE,
)
_PROPOSITION_PREFIX = re.compile(
    r"^(?:regeringens\s+)?proposition(?:en)?\s+om\s+",
    re.IGNORECASE,
)
_HEADER_LINE = re.compile(
    r"^(?:#+|\d+\.)\s+|"
    r"^regeringens\s+proposition|"
    r"^prop\.\s*\d{4}|"
    r"^sou\s+\d{4}:"
    r"|^nr\.?\s*\d+\s*$|"
    r"^beslutad\s+den\s+|"
    r"^(?:propositionens\s+)?huvudsaklig(?:t|a)\s+innehåll\b",
    re.IGNORECASE,
)
_SUMMARY_HEADING = re.compile(
    r"^(?:#+\s*)?(?:propositionens\s+)?huvudsaklig(?:t|a)\s+innehåll\b",
    re.IGNORECASE,
)

MIN_BODY_CHARS = 80
WINDOW_CHARS = 1600


def _plain(value: str) -> str:
    return _HTML_TAG.sub("", value).replace("&#x2F;", "/").strip()


def _compact(value: str) -> str:
    return " ".join(_plain(value).split())


def _tokens(value: str) -> frozenset[str]:
    return frozenset(match.group(0).casefold() for match in _TOKEN.finditer(value))


def citation_from_lagen_nu_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    if match := _PROP_PATH.search(uri):
        year, suffix, number = match.groups()
        return f"Prop. {year}/{suffix}:{number}" if suffix else f"Prop. {year}:{number}"
    if match := _SOU_PATH.search(uri):
        return f"SOU {match.group(1)}:{match.group(2)}"
    if match := _DS_PATH.search(uri):
        return f"Ds {match.group(1)}:{match.group(2)}"
    if match := _BET_PATH.search(uri):
        return f"Bet. {match.group(1)}"
    if match := _DIR_PATH.search(uri):
        return f"Dir. {match.group(1)}:{match.group(2)}"
    if match := _NJA_PATH.search(uri):
        return f"NJA {match.group(1)} s. {match.group(2)}"
    if match := _SFS_PATH.search(uri):
        path = uri.split("lagen.nu/", 1)[-1]
        if path.startswith(("prop/", "sou/", "ds/", "bet/", "dir/", "dom/", "lr/")):
            return None
        return f"SFS {match.group(1)}:{match.group(2)}"
    return None


def citation_from_text(value: str | None) -> str | None:
    if not value:
        return None
    match = _TEXT_CITATION.search(value)
    if match is None:
        return None
    return re.sub(r"\s+", " ", match.group(0)).replace("prop.", "Prop.").replace("sou ", "SOU ")


def _capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _short_descriptive(title: str | None, citation: str | None) -> str | None:
    if not title:
        return None
    text = _compact(title)
    text = _PROPOSITION_PREFIX.sub("", text)
    text = re.sub(r"(?:\s*m\.m\.)+$", "", text, flags=re.IGNORECASE).strip(" ;,.—-")
    if citation and text.casefold() == citation.casefold():
        return None
    return _capitalize_first(text) if text else None


def _citation_already_in(citation: str, descriptive: str) -> bool:
    if citation.casefold() in descriptive.casefold():
        return True
    number = re.search(r"(\d{4}(?:/\d{2})?:\d+)$", citation)
    return bool(number and number.group(1) in descriptive)


def display_source_title(
    *,
    uri: str | None,
    identifier: str | None = None,
    title: str | None = None,
) -> str | None:
    citation = (
        citation_from_lagen_nu_uri(uri)
        or citation_from_text(identifier)
        or citation_from_text(title)
    )
    descriptive = _short_descriptive(title, citation)
    if citation and descriptive and not _citation_already_in(citation, descriptive):
        return f"{citation} — {descriptive}"
    return descriptive or citation or title


def is_legal_front_matter(text: str | None, *, title: str | None = None) -> bool:
    if not text or not text.strip():
        return True
    compact = _compact(text)
    if _SUMMARY_HEADING.match(compact):
        return True
    if not _HEADER_NOISE.search(compact):
        return False
    residual = _HEADER_NOISE.sub(" ", compact)
    if title:
        residual = re.sub(re.escape(_compact(title)), " ", residual, flags=re.IGNORECASE)
        short = _short_descriptive(title, citation_from_text(title))
        if short:
            residual = re.sub(re.escape(short), " ", residual, flags=re.IGNORECASE)
    return len(_compact(residual)) < MIN_BODY_CHARS


def _term_overlap(terms: frozenset[str], value: str) -> int:
    if not terms:
        return 0
    return len(terms & _tokens(value))


def _after_header_lines(text: str) -> str:
    lines = text.splitlines()
    index = 0
    while index < len(lines) and (
        not lines[index].strip() or _HEADER_LINE.match(lines[index].strip())
    ):
        index += 1
    return "\n".join(lines[index:]).strip()


def _best_window(text: str, terms: frozenset[str]) -> str:
    if not text:
        return ""
    if not terms:
        return text[:WINDOW_CHARS]
    lowered = text.casefold()
    best_start = 0
    best_score = -1
    for term in terms:
        start = 0
        while True:
            found = lowered.find(term, start)
            if found < 0:
                break
            window_start = max(0, found - 160)
            chunk = text[window_start : window_start + WINDOW_CHARS]
            score = _term_overlap(terms, chunk)
            if score > best_score:
                best_score = score
                best_start = window_start
            start = found + len(term)
    if best_score <= 0:
        return text[:WINDOW_CHARS]
    return text[best_start : best_start + WINDOW_CHARS].strip()


def selector_passage_text(
    text: str,
    *,
    needles: frozenset[str],
    title: str | None = None,
    max_chars: int,
) -> str:
    """Windows around provision/need terms so the selector never sees only the cover."""
    body = _plain(text)
    windows = _windows_around_needles(body, needles, max_chars=max_chars)
    if windows:
        return windows
    skipped = relevant_legal_excerpt(
        body, terms=_tokens(" ".join(needles)), title=title, max_chars=max_chars
    )
    if skipped and not is_legal_front_matter(skipped, title=title):
        return skipped
    after = _after_header_lines(body)
    return (after or body)[:max_chars]


def _windows_around_needles(
    text: str,
    needles: frozenset[str],
    *,
    max_chars: int,
) -> str:
    provision = {item for item in needles if "§" in item}
    spans = _needle_spans(text, provision) or _needle_spans(text, needles)
    if not spans:
        return ""
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    parts: list[str] = []
    used = 0
    for start, end in merged:
        chunk = text[start:end].strip()
        if not chunk or is_legal_front_matter(chunk):
            continue
        if used + len(chunk) > max_chars:
            remain = max_chars - used
            if remain >= MIN_BODY_CHARS:
                parts.append(chunk[:remain])
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n\n".join(parts)


def _needle_spans(text: str, needles: frozenset[str]) -> list[tuple[int, int]]:
    lowered = text.casefold()
    spans: list[tuple[int, int]] = []
    for needle in needles:
        target = needle.casefold().strip()
        if len(target) < 2:
            continue
        start = 0
        while True:
            found = lowered.find(target, start)
            if found < 0:
                break
            spans.append(
                (
                    max(0, found - 200),
                    min(len(text), found + len(target) + WINDOW_CHARS - 200),
                )
            )
            start = found + len(target)
    return spans


def relevant_legal_excerpt(
    text: str,
    *,
    terms: frozenset[str] = frozenset(),
    title: str | None = None,
    max_chars: int = WINDOW_CHARS,
) -> str:
    body = _after_header_lines(_plain(text))
    if not body:
        body = _plain(text)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    usable = [
        part for part in paragraphs if not is_legal_front_matter(part, title=title)
    ]
    pool = usable or paragraphs
    if terms and pool:
        ranked = sorted(pool, key=lambda part: (-_term_overlap(terms, part), len(part)))
        if _term_overlap(terms, ranked[0]) > 0:
            return ranked[0][:max_chars]
    if pool:
        substantial = next(
            (part for part in pool if len(_compact(part)) >= MIN_BODY_CHARS),
            pool[0],
        )
        if not is_legal_front_matter(substantial, title=title):
            return substantial[:max_chars]
    return _best_window(body, terms)[:max_chars]


def choose_legal_excerpt(
    *,
    document_text: str,
    hit_excerpt: str | None,
    terms: frozenset[str],
    title: str | None,
    max_chars: int,
) -> str:
    from_document = relevant_legal_excerpt(
        document_text, terms=terms, title=title, max_chars=max_chars
    )
    candidates = [hit_excerpt or "", from_document, document_text]
    for candidate in candidates:
        text = _compact(candidate)
        if text and not is_legal_front_matter(text, title=title):
            return candidate.strip()[:max_chars]
    return (from_document or hit_excerpt or document_text)[:max_chars]
