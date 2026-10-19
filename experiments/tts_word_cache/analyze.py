"""Repetition analysis: word-level vs segment-level TTS caching.

Runs the exact production `SpeechSegmenter` (first_target=110, max_chars=220) over a
documented, offline Swedish corpus and measures how many TTS calls (and characters) a
segment-level cache can save versus the theoretical ceiling of a word-level cache.

Deterministic by construction: fixed source list, sorted iteration, no network, no
randomness, no timestamps. Running twice produces byte-identical results.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

sys.path.insert(0, str(BACKEND))
from app.services.speech_segmenter import SpeechSegmenter  # noqa: E402

FIRST_TARGET = 110
MAX_CHARS = 220

_TESTS_WITH_SWEDISH_ANSWERS = [
    "tests/test_live_speech.py",
    "tests/test_live_speech_conversation.py",
    "tests/test_live_voice.py",
    "tests/test_gemini_live.py",
    "tests/test_sme.py",
    "tests/test_sme_group_voice.py",
    "tests/test_sme_group_voice_barge.py",
    "tests/test_sme_open_document.py",
    "tests/test_sme_panel_channel.py",
    "tests/test_sme_quick_draft.py",
    "tests/test_sme_quick_draft_service.py",
    "tests/test_voice_workspace_inbox.py",
    "tests/test_voice_workspace_membership.py",
    "tests/test_voice_workspace_research_bridge.py",
    "tests/test_voice_workspace_returning.py",
    "tests/test_voice_workspaces.py",
    "tests/test_workspace_chat.py",
    "tests/test_elevenlabs_live.py",
    "tests/fixture_module.py",
]

_TOKEN = re.compile(r"[a-zåäöéü0-9]+")
_HAS_LETTER = re.compile(r"[a-zåäöéü]")
_DOMAIN_CORE_GROUPS = ("sme-story", "golden-questions", "sme-docs", "backend-tests")
_SWEDISH_MARKER = re.compile(
    r"å|ä|ö|och|att|det|är|inte|som|har|med|för|ska|kan|vill|hej|tack|avtal|kund|bolag"
    r"|fråga|svar",
    re.IGNORECASE,
)
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_FENCE = re.compile(r"```.*?```", re.DOTALL)


def clean_markdown(text: str) -> str:
    """Drop frontmatter, fenced code and table separator rows; keep prose."""
    text = _FRONTMATTER.sub("", text)
    text = _FENCE.sub(" ", text)
    lines = [
        line
        for line in text.splitlines()
        if not ("-" in line and re.fullmatch(r"[\s|:\-]+", line))
    ]
    return "\n".join(lines)


def dedupe(texts: list[str]) -> list[str]:
    """Drop exact duplicates within a group, keeping first-occurrence order."""
    return list(dict.fromkeys(texts))


def story_texts() -> list[str]:
    truth = json.loads((ROOT / "synthetic_sme/ground_truth/truth_model.json").read_text())
    facts = json.loads((ROOT / "synthetic_sme/generator/data/facts.json").read_text())
    texts = [f"{e['title']}. {e['description']}" for e in truth["events"]]
    texts += [a["description"] for a in facts["anomalies"]]
    return dedupe(texts)


def question_texts() -> list[str]:
    questions = json.loads(
        (ROOT / "synthetic_sme/golden_questions/golden_questions.json").read_text()
    )
    return dedupe([q["question"] for q in questions])


def sme_doc_texts() -> list[str]:
    files = [
        ROOT / "synthetic_sme/README.md",
        ROOT / "synthetic_sme/validation/validation_report.md",
    ]
    return dedupe([clean_markdown(path.read_text()) for path in files])


def manual_texts() -> list[str]:
    files = sorted((ROOT / "knowledge/manual").glob("*.md"))
    return dedupe([clean_markdown(path.read_text()) for path in files])


def test_answer_texts() -> list[str]:
    """String literals from voice/SME tests that look like spoken Swedish answers."""
    texts: list[str] = []
    for relative in _TESTS_WITH_SWEDISH_ANSWERS:
        tree = ast.parse((BACKEND / relative).read_text())
        for node in ast.walk(tree):
            value = node.value if isinstance(node, ast.Constant) else None
            if not isinstance(value, str):
                continue
            if len(re.findall(r"[a-zA-ZåäöÅÄÖéü]+", value)) < 3:
                continue
            if len(_SWEDISH_MARKER.findall(value)) >= 2:
                texts.append(value)
    return dedupe(texts)


def sources() -> dict[str, list[str]]:
    return {
        "sme-story": story_texts(),
        "golden-questions": question_texts(),
        "sme-docs": sme_doc_texts(),
        "operator-manuals": manual_texts(),
        "backend-tests": test_answer_texts(),
    }


def segment(text: str) -> list[str]:
    segmenter = SpeechSegmenter(first_target=FIRST_TARGET, max_chars=MAX_CHARS)
    segments = segmenter.push(text)
    segments += segmenter.finish()
    return segments


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def group_stats(texts: list[str]) -> dict:
    """Segment-level and word-level repetition stats for one source group."""
    segments: list[str] = []
    for text in texts:
        segments.extend(segment(text))
    words = [word for segment in segments for word in tokens(segment)]
    return {
        "texts": len(texts),
        "text_chars": sum(len(text) for text in texts),
        "segments": segment_stats(segments),
        "words": word_stats(words),
    }


def flat_lists(grouped: dict[str, list[str]], names: tuple[str, ...] | None = None) -> tuple[list[str], list[str]]:
    """All segments and words across groups (or a named subset), in stable order."""
    segments: list[str] = []
    words: list[str] = []
    for name, texts in grouped.items():
        if names is not None and name not in names:
            continue
        for text in texts:
            for spoken in segment(text):
                segments.append(spoken)
                words.extend(tokens(spoken))
    return segments, words


def assemblable_segments(segments: list[str], words: list[str]) -> dict:
    """Segments whose every token has already been seen once in the word counter."""
    counts = Counter(words)
    served = [s for s in segments if all(counts[t] >= 2 for t in tokens(s))]
    return {
        "count": len(served),
        "total": len(segments),
        "rate_calls": len(served) / len(segments) if segments else 0.0,
    }


def aggregate(grouped: dict[str, list[str]], names: tuple[str, ...]) -> dict:
    segments, words = flat_lists(grouped, names)
    return {
        "segments": segment_stats(segments),
        "words": word_stats(words),
        "segments_fully_assemblable": assemblable_segments(segments, words),
    }


def segment_stats(segments: list[str]) -> dict:
    counts = Counter(segments)
    total = len(segments)
    unique = len(counts)
    chars_total = sum(len(segment) for segment in segments)
    chars_repeated = sum(
        len(segment) for segment in segments if counts[segment] >= 2
    )
    top = [
        {"text": text, "count": count, "chars": len(text)}
        for text, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= 2
    ][:15]
    return {
        "total": total,
        "unique": unique,
        "repeated_instances": total - unique,
        "repetition_rate_calls": (total - unique) / total if total else 0.0,
        "chars_total": chars_total,
        "chars_repeated": chars_repeated,
        "repetition_rate_chars": chars_repeated / chars_total if chars_total else 0.0,
        "top_repeated": top,
    }


def word_stats(words: list[str]) -> dict:
    counts = Counter(words)
    total = len(words)
    unique = len(counts)
    chars_total = sum(len(word) for word in words)
    chars_repeated = sum(len(word) for word in words if counts[word] >= 2)
    top = [
        {"word": word, "count": count}
        for word, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= 2
    ][:20]
    alpha = [word for word in words if _HAS_LETTER.search(word)]
    alpha_counts = Counter(alpha)
    alpha_total = len(alpha)
    return {
        "total": total,
        "unique": unique,
        "repeated_instances": total - unique,
        "repetition_rate_calls": (total - unique) / total if total else 0.0,
        "chars_total": chars_total,
        "chars_repeated": chars_repeated,
        "repetition_rate_chars": chars_repeated / chars_total if chars_total else 0.0,
        "top_words": top,
        "alpha_only": {
            "total": alpha_total,
            "unique": len(alpha_counts),
            "repetition_rate_calls": (alpha_total - len(alpha_counts)) / alpha_total
            if alpha_total
            else 0.0,
        },
    }


def build_report() -> dict:
    grouped = sources()
    per_source = {name: group_stats(texts) for name, texts in grouped.items()}
    flat_segments, flat_words = flat_lists(grouped)
    words = word_stats(flat_words)
    words["segments_fully_assemblable"] = assemblable_segments(flat_segments, flat_words)
    return {
        "meta": {
            "purpose": (
                "How much a segment-level TTS cache saves vs the theoretical ceiling "
                "of a word-level cache, on the Swedish SME live-voice domain."
            ),
            "segmenter": {
                "module": "backend/app/services/speech_segmenter.py",
                "first_target": FIRST_TARGET,
                "max_chars": MAX_CHARS,
            },
            "sources": {
                name: {"texts": stats["texts"], "chars": stats["text_chars"]}
                for name, stats in per_source.items()
            },
        },
        "segments": segment_stats(flat_segments),
        "words": words,
        "domain_core": aggregate(grouped, _DOMAIN_CORE_GROUPS),
        "per_source": per_source,
    }


def write_results(report: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / "analysis.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    summary_path = RESULTS_DIR / "summary.md"
    summary_path.write_text(render_summary(report))


def render_summary(report: dict) -> str:
    segments = report["segments"]
    words = report["words"]
    core = report["domain_core"]
    per = report["per_source"]

    def pct(rate: float) -> str:
        return f"{rate * 100:.1f} %"

    def level_row(label: str, stats: dict) -> str:
        return (
            f"| {label} | {stats['total']} | {stats['unique']} | "
            f"{stats['repeated_instances']} | {pct(stats['repetition_rate_calls'])} | "
            f"{pct(stats['repetition_rate_chars'])} |"
        )

    source_rows = "\n".join(
        f"| {name} | {stats['texts']} | {stats['text_chars']} | "
        f"{stats['segments']['total']} | {stats['segments']['unique']} | "
        f"{pct(stats['segments']['repetition_rate_calls'])} | "
        f"{stats['words']['total']} | {stats['words']['unique']} | "
        f"{pct(stats['words']['repetition_rate_calls'])} |"
        for name, stats in per.items()
    )
    top_segments = "\n".join(
        f"{i + 1}. `{item['text'][:110]}` — {item['count']}×"
        for i, item in enumerate(segments["top_repeated"][:10])
    )
    top_words = ", ".join(
        f"{item['word']} ({item['count']}×)" for item in words["top_words"][:10]
    )
    return f"""# TTS repetition analysis — segment level vs word level

Generated deterministically by `analyze.py` from the checked-in corpus. Offline; no API calls.

## Headline numbers

| Level | Total | Unique | Repeated instances | Call share saved | Char share saved |
| ----- | ----- | ------ | ------------------ | ---------------- | ---------------- |
{level_row("Segments (cache unit)", segments)}
{level_row("Words (theoretical ceiling)", words)}

Words, alpha-only tokens (numbers/dates excluded): {words['alpha_only']['total']} total,
{words['alpha_only']['unique']} unique, repeat call share {pct(words['alpha_only']['repetition_rate_calls'])}.

Segments a perfect word cache could serve entirely from cached words (every token seen
before in the corpus): {words['segments_fully_assemblable']['count']} of
{words['segments_fully_assemblable']['total']}
({pct(words['segments_fully_assemblable']['rate_calls'])}) — assuming perfect splicing
and ignoring prosody.

## Domain core (live-voice domain; operator manuals excluded)

| Level | Total | Unique | Repeated instances | Call share saved | Char share saved |
| ----- | ----- | ------ | ------------------ | ---------------- | ---------------- |
{level_row("Segments (cache unit)", core['segments'])}
{level_row("Words (theoretical ceiling)", core['words'])}

Segments a perfect word cache could serve entirely from cached words:
{core['segments_fully_assemblable']['count']} of {core['segments_fully_assemblable']['total']}
({pct(core['segments_fully_assemblable']['rate_calls'])}).

## Per source

| Source | Texts | Chars | Segments | Unique seg. | Seg. repeat | Words | Unique words | Word repeat |
| ------ | ----- | ----- | -------- | ----------- | ----------- | ----- | ------------ | ----------- |
{source_rows}

## Top repeated segments

{top_segments}

## Top words

{top_words}

## Interpretation

- A segment-level cache saves {pct(segments['repetition_rate_calls'])} of TTS calls and
  {pct(segments['repetition_rate_chars'])} of billed characters on a warm cache. In the
  live-voice domain core the segment repeat rate is even lower
  ({pct(core['segments']['repetition_rate_calls'])} calls / {pct(core['segments']['repetition_rate_chars'])} chars).
- A perfect word-level cache could at most save {pct(words['repetition_rate_calls'])} of
  word synthesis calls ({pct(words['repetition_rate_chars'])} of characters), and only
  {words['segments_fully_assemblable']['count']} of {words['segments_fully_assemblable']['total']}
  segments ({pct(words['segments_fully_assemblable']['rate_calls'])}) would become fully
  cache-served — and each must be reassembled from isolated or aligned word audio
  (destroyed or mismatched prosody, see docs/guides/tts-word-cache.md). The ceiling is
  therefore not reachable at acceptable quality; the segment cache captures the
  reachable part with zero audio surgery.
"""


def main() -> None:
    report = build_report()
    write_results(report)
    segments = report["segments"]
    words = report["words"]
    print(
        f"segments: {segments['total']} total, {segments['unique']} unique, "
        f"{segments['repetition_rate_calls'] * 100:.1f}% call share repeated, "
        f"{segments['repetition_rate_chars'] * 100:.1f}% char share repeated"
    )
    print(
        f"words: {words['total']} total, {words['unique']} unique, "
        f"{words['repetition_rate_calls'] * 100:.1f}% call share repeated, "
        f"{words['repetition_rate_chars'] * 100:.1f}% char share repeated"
    )
    print(f"wrote {RESULTS_DIR / 'analysis.json'} and {RESULTS_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
