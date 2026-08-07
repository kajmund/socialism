"""Versioned Swedish SSR anchor statements for tone and message style."""

from __future__ import annotations

from dataclasses import dataclass

# Bump when anchors change — persisted in quick-report tech appendix / ssr.json.
ANCHOR_SET_VERSION = "v1"

# Stable style keys (Swedish); UI may translate via locale.display_style_label.
STYLE_LABELS: tuple[str, ...] = (
    "Sarkastisk + konkret kritik",
    "Uppgiven + vardagsmetafor",
    "Fakta + yrkesauktoritet",
    "Personlig + hjärtlig berättelse",
    "Optimistisk / lösningsfokuserad",
    "Provocerande / konfronterande",
)

STYLE_UNCLASSIFIED = "Oklassad"

# 5-level tone scale (SSR Likert). Labels used in tone_shares / charts.
TONE_LABELS_SV: tuple[str, ...] = (
    "Starkt negativ",
    "Något negativ",
    "Neutral",
    "Något positiv",
    "Starkt positiv",
)

TONE_LABELS_EN: tuple[str, ...] = (
    "Strongly negative",
    "Somewhat negative",
    "Neutral",
    "Somewhat positive",
    "Strongly positive",
)


@dataclass(frozen=True)
class AnchorSet:
    name: str
    version: str
    labels: tuple[str, ...]
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.labels) != len(self.statements):
            raise ValueError(
                f"AnchorSet {self.name}: labels ({len(self.labels)}) "
                f"!= statements ({len(self.statements)})"
            )


# Political/opinion domain — not product-review wording from the Maier paper.
TONE_ANCHORS_SV = AnchorSet(
    name="tone_sv",
    version=ANCHOR_SET_VERSION,
    labels=TONE_LABELS_SV,
    statements=(
        "Texten uttrycker starkt negativ, kritisk eller uppgiven hållning till budskapet.",
        "Texten lutar åt negativ eller skeptisk ton, men utan total avfärdning.",
        "Texten är neutral, obeslutsam eller saknar tydlig värdering av budskapet.",
        "Texten lutar åt positiv, konstruktiv eller hoppfull ton.",
        "Texten uttrycker starkt positivt, stöttande eller entusiastiskt mottagande.",
    ),
)

TONE_ANCHORS_EN = AnchorSet(
    name="tone_en",
    version=ANCHOR_SET_VERSION,
    labels=TONE_LABELS_EN,
    statements=(
        "The text expresses a strongly negative, critical, or resigned stance toward the message.",
        "The text leans negative or skeptical, but without total rejection.",
        "The text is neutral, undecided, or lacks a clear evaluation of the message.",
        "The text leans positive, constructive, or hopeful.",
        "The text expresses strongly positive, supportive, or enthusiastic reception.",
    ),
)

STYLE_ANCHORS_SV = AnchorSet(
    name="style_sv",
    version=ANCHOR_SET_VERSION,
    labels=STYLE_LABELS,
    statements=(
        "Sarkastisk eller ironisk ton med konkret kritik, ofta med siffror eller skarp iakttagelse.",
        "Uppgiven eller trött ton med vardagsmetaforer om hur saker läcker eller inte fungerar.",
        "Faktadriven och auktoritetsbaserad stil som hänvisar till källor, forskning eller data.",
        "Personlig och hjärtlig berättelse med egna erfarenheter eller känslor.",
        "Optimistisk och lösningsfokuserad stil som pekar framåt och mot gemensamma lösningar.",
        "Provocerande eller konfronterande språk som anklagar, skäms ut eller eskalerar konflikten.",
    ),
)

STYLE_ANCHORS_EN = AnchorSet(
    name="style_en",
    version=ANCHOR_SET_VERSION,
    labels=STYLE_LABELS,
    statements=(
        "Sarcastic or ironic tone with concrete criticism, often with numbers or sharp observation.",
        "Resigned or weary tone with everyday metaphors about things leaking or not working.",
        "Fact-driven, authority-based style that cites sources, research, or data.",
        "Personal and warm storytelling with lived experience or feelings.",
        "Optimistic, solution-focused style that looks forward and toward joint solutions.",
        "Provocative or confrontational language that blames, shames, or escalates conflict.",
    ),
)


def tone_anchors(*, locale: str = "sv") -> AnchorSet:
    return TONE_ANCHORS_EN if locale == "en" else TONE_ANCHORS_SV


def style_anchors(*, locale: str = "sv") -> AnchorSet:
    return STYLE_ANCHORS_EN if locale == "en" else STYLE_ANCHORS_SV


def tone_labels(*, locale: str = "sv") -> tuple[str, ...]:
    return tone_anchors(locale=locale).labels
