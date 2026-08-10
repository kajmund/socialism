"""Numbered footnotes and glossary for snabbrapport HTML."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from app.services.report.locale import ReportLocale


@dataclass(frozen=True)
class GlossaryEntry:
    id: str
    term_sv: str
    term_en: str
    body_sv: str
    body_en: str


ENTRIES: tuple[GlossaryEntry, ...] = (
    GlossaryEntry(
        id="likes-total",
        term_sv="Likes totalt",
        term_en="Total likes",
        body_sv=(
            "Summan av likes på alla inlägg och alla kommentarer i simuleringen "
            "(injektor och population)."
        ),
        body_en=(
            "Sum of likes on all posts and all comments in the simulation "
            "(injector and population)."
        ),
    ),
    GlossaryEntry(
        id="likes-injection",
        term_sv="Likes på testbudskap",
        term_en="Likes on test message",
        body_sv=(
            "Likes på inlägg vars text matchar det injicerade budskapet, "
            "eller som postats av injektorn (partikontot)."
        ),
        body_en=(
            "Likes on posts whose text matches the injected message, "
            "or posted by the injector account."
        ),
    ),
    GlossaryEntry(
        id="engagement-score",
        term_sv="Engagemangspoäng",
        term_en="Engagement score",
        body_sv=(
            "likes totalt + 2 × antal kommentarer + 3 × antal delningar. "
            "Delningar räknas bara på inlägg."
        ),
        body_en=(
            "total likes + 2 × comment count + 3 × share count. "
            "Shares are counted on posts only."
        ),
    ),
    GlossaryEntry(
        id="segment-score",
        term_sv="Segmentpoäng",
        term_en="Segment score",
        body_sv=(
            "I målgruppsanalys: per agent summeras mottagna inläggslikes, "
            "kommentarslikes, delningar (×2) och antal kommentarer (×2); "
            "sedan summa för segmentet. Annan formel än engagemangspoäng i tabellen."
        ),
        body_en=(
            "In target-group analysis: per agent, received post likes, comment likes, "
            "shares (×2), and comment count (×2) are summed; then totaled for the segment. "
            "Different formula from the table engagement score."
        ),
    ),
    GlossaryEntry(
        id="zero-likes",
        term_sv="0 likes (deltagare)",
        term_en="0 likes (participants)",
        body_sv=(
            "Population-agenter vars egna inlägg och kommentarer aldrig fick likes — "
            "inte agenter som själva inte gillade något."
        ),
        body_en=(
            "Population agents whose own posts and comments never received likes — "
            "not agents who did not like anything themselves."
        ),
    ),
    GlossaryEntry(
        id="gini",
        term_sv="Ojämlikhet (Gini)",
        term_en="Inequality (Gini)",
        body_sv=(
            "Hur ojämnt mottagna likes fördelas mellan population-agenter "
            "(0 = jämnt, 1 = en agent tar allt). Injektor exkluderad."
        ),
        body_en=(
            "How unevenly received likes are distributed among population agents "
            "(0 = even, 1 = one agent takes all). Injector excluded."
        ),
    ),
    GlossaryEntry(
        id="positive-tone",
        term_sv="Positiv / kritisk ton",
        term_en="Positive / critical tone",
        body_sv=(
            "Femnivåskala via SSR (semantisk likhet mot tonankare) på de mest "
            "gillade reaktionstexterna — inlägg och kommentarer i urval, inte hela flödet."
        ),
        body_en=(
            "Five-level scale via SSR (semantic similarity to tone anchors) on the "
            "top-liked reaction texts — a sample of posts and comments, not the full feed."
        ),
    ),
    GlossaryEntry(
        id="style-likes",
        term_sv="Snittlikes per stil",
        term_en="Average likes per style",
        body_sv=(
            "SSR-klassificerad budskapsstil: viktat medel av likes på reaktioner "
            "som liknar stilen (en text kan räknas delvis i flera stilar)."
        ),
        body_en=(
            "SSR-classified message style: weighted average of likes on reactions "
            "similar to the style (one text may count partly toward several styles)."
        ),
    ),
    GlossaryEntry(
        id="simulated-support",
        term_sv="Simulerat stöd (0–100)",
        term_en="Simulated support (0–100)",
        body_sv=(
            "Intern regelpoäng för rekommendation (ton, likes på testbudskap, "
            "engagemang) — inte väljarstöd eller opinionsmätning."
        ),
        body_en=(
            "Internal rule-based score for the recommendation (tone, test-message likes, "
            "engagement) — not voter support or a poll."
        ),
    ),
    GlossaryEntry(
        id="topic-share",
        term_sv="Ämnesfördelning",
        term_en="Topic distribution",
        body_sv=(
            "Nyckelordsmatchning mot ämnen härledda från testbudskapet (quick mode, ingen LLM)."
        ),
        body_en=(
            "Keyword matching against topics derived from test messages (quick mode, no LLM)."
        ),
    ),
    GlossaryEntry(
        id="topic-drift",
        term_sv="Ämnesdrift",
        term_en="Topic drift",
        body_sv=(
            "Nyckelordsandel för testämnet i populationens inlägg: första tredjedelen "
            "≈ dag 1 jämfört med resten. Flagga om andelen sjunker under 10 %."
        ),
        body_en=(
            "Keyword share for the test topic in population posts: first third ≈ day 1 "
            "vs the remainder. Flagged when share drops below 10%."
        ),
    ),
    GlossaryEntry(
        id="agent-likes",
        term_sv="Likes mottagna (agent)",
        term_en="Likes received (agent)",
        body_sv=(
            "Summan av likes på agentens egna inlägg och kommentarer; "
            "genomsnitt per inlägg/kommentar visas separat."
        ),
        body_en=(
            "Sum of likes on the agent's own posts and comments; "
            "average per post/comment shown separately."
        ),
    ),
    GlossaryEntry(
        id="shares-dislikes",
        term_sv="Delningar / dislikes",
        term_en="Shares / dislikes",
        body_sv=(
            "Delningar räknas på inlägg. Dislikes på inlägg och kommentarer."
        ),
        body_en="Shares are counted on posts. Dislikes on posts and comments.",
    ),
    GlossaryEntry(
        id="ab-relative",
        term_sv="A/B-relativa staplar",
        term_en="A/B relative bars",
        body_sv=(
            "Stapelns längd är relativ inom varje mått (längsta arm = 100 %) — "
            "inte statistisk signifikans."
        ),
        body_en=(
            "Bar length is relative within each metric (longest arm = 100%) — "
            "not statistical significance."
        ),
    ),
    GlossaryEntry(
        id="ssr",
        term_sv="SSR",
        term_en="SSR",
        body_sv=(
            "Semantic Similarity Rating: ton och stil via textembeddings "
            "mot referensankare (OpenAI text-embedding-3-large)."
        ),
        body_en=(
            "Semantic Similarity Rating: tone and style via text embeddings "
            "against reference anchors (OpenAI text-embedding-3-large)."
        ),
    ),
    GlossaryEntry(
        id="silent-day",
        term_sv="Tyst dag",
        term_en="Silent day",
        body_sv=(
            "Simuleringstick utan nytt budskag; debatten kan fortsätta på tidigare inlägg."
        ),
        body_en=(
            "Simulation tick with no new message injection; debate may continue on prior posts."
        ),
    ),
    GlossaryEntry(
        id="simulated-not-real",
        term_sv="Simulerat ≠ verkligt",
        term_en="Simulated ≠ real",
        body_sv="AI-agenter modellerar beteende — de är inte riktiga väljare.",
        body_en="AI agents model behavior — they are not real voters.",
    ),
)

_INDEX: dict[str, int] = {entry.id: idx + 1 for idx, entry in enumerate(ENTRIES)}


def footnote(entry_id: str) -> str:
    """Superscript link to a glossary entry."""
    number = _INDEX[entry_id]
    return f'<sup class="fn"><a href="#fn-{entry_id}">{number}</a></sup>'


def glossary_hint(*, locale: ReportLocale) -> str:
    if locale == "en":
        return '<p class="glossary-hint">Numbered markers refer to the glossary at the end.</p>'
    return '<p class="glossary-hint">Numrerade markörer förklaras i ordlistan längst ner.</p>'


def render_quick_glossary(*, locale: ReportLocale) -> str:
    title = "Glossary" if locale == "en" else "Ordlista"
    items: list[str] = []
    for entry in ENTRIES:
        term = entry.term_en if locale == "en" else entry.term_sv
        body = entry.body_en if locale == "en" else entry.body_sv
        number = _INDEX[entry.id]
        items.append(
            f'<div class="gloss-item" id="fn-{entry.id}">'
            f'<span class="gloss-n">{number}.</span> '
            f"<strong>{escape(term)}</strong> — "
            f"<span>{escape(body)}</span></div>"
        )
    return (
        f'<section class="glossary" id="ordlista">'
        f"<h3>{escape(title)}</h3>"
        f'{"".join(items)}'
        f"</section>"
    )
