"""Isolated answer_cell instruction variants. Default path stays P0."""

from __future__ import annotations

from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND, UNCERTAIN
from overgraph_ingest.tabular.gold import USER_QUESTIONS
from overgraph_ingest.tabular.jev_io import P0_STATUS_CRITERIA, P0_STATUS_INSTRUCTIONS

PROMPT_P0 = "P0"
PROMPT_P1 = "P1"
PROMPT_P2 = "P2"
PROMPT_P3 = "P3"
PROMPT_P0_EN = "P0_EN"
PROMPT_P0_V2_B = "P0_v2_B"
PROMPT_P0_V2 = "P0_v2"
PROMPT_P0_V2_D = "P0_v2_D"
PROMPT_P0_V2_EN = "P0_v2_en"
PROMPT_IDS = (PROMPT_P0, PROMPT_P1, PROMPT_P2, PROMPT_P3)

ENGLISH_QUESTIONS = {
    "auto-renewal": "Does the agreement renew automatically?",
    "notice-period": "What notice period applies under the agreement?",
    "liability-cap": "Is there a limitation on the parties' liability for damages?",
    "confidentiality": "Is there a confidentiality obligation in the agreement?",
    "liability-secrecy-carveout": "Is a breach of confidentiality excluded from the liability limitation?",
}

INSTRUCTIONS = {
    PROMPT_P0: P0_STATUS_INSTRUCTIONS,
    PROMPT_P1: (
        "{question} "
        "Answer only from examined units. "
        "ANSWERED requires choosing a listed excerpt that is an exact substring. "
        "Shared topic words or a nearby clause are not enough. "
        "ANSWERED only if the excerpt states the same contractual term the question asks for."
    ),
    PROMPT_P2: (
        "{question} "
        "Answer only from examined units. "
        "ANSWERED requires choosing a listed excerpt that is an exact substring. "
        "Name the legal relation the excerpt actually creates. "
        "ANSWERED only if that relation is the one the question asks for."
    ),
    PROMPT_P3: (
        "{question} "
        "Answer only from examined units. "
        "ANSWERED requires choosing a listed excerpt that is an exact substring. "
        "The excerpt's scope must match the question's scope. "
        "A narrower addendum, a wider heading, or a different party's duty is NOT_FOUND."
    ),
}

HYPOTHESES = {
    PROMPT_P0: "Frozen answer_cell instruction.",
    PROMPT_P1: "Topic similarity is not the asked term.",
    PROMPT_P2: "Name the legal relation before answering.",
    PROMPT_P3: "Answer scope must match question scope.",
}


P0_V2_DEFINITIONS = (
    "{question}\n\n"
    "Undersök alla fem TextUnits innan du väljer status.\n\n"
    "Status:\n"
    "- ANSWERED: minst ett utdrag besvarar frågan direkt, så som den är "
    "formulerad. Utdraget ska själv uttrycka regeln eller svaret. Det räcker "
    "inte att det rör samma ämne, använder samma nyckelord eller liknar "
    "svaret. Utdraget måste vara en exakt delsträng av en av de fem TextUnits.\n"
    "- UNCERTAIN: materialet rör frågans ämne men besvarar den inte säkert. "
    "Använd detta när utdragen bara är närliggande (t.ex. ett snävt undantag "
    "eller en sanktion i stället för en generell regel), när de säger olika "
    "saker, eller när det bara finns rubriker eller hänvisningar utan själva "
    "regeln.\n"
    "- NOT_FOUND: inget av utdragen rör frågans ämne alls."
)

P0_V2_DECISION = (
    "\n\nBeslut:\n"
    "1. Finns ett utdrag som i sig själv besvarar frågan? Då ANSWERED.\n"
    "2. Annars: rör något utdrag ämnet? Då UNCERTAIN.\n"
    "3. Annars: NOT_FOUND.\n\n"
    "Om flera utdrag är relevanta, välj det som själv uttrycker regeln, inte "
    "det som hänvisar till den eller omger den.\n"
    "Ett närliggande utdrag är aldrig ANSWERED."
)

P0_V2_EN_DEFINITIONS = (
    "{question}\n\n"
    "Examine all five TextUnits before choosing a status.\n\n"
    "Status:\n"
    "- ANSWERED: at least one excerpt answers the question directly, as it is "
    "worded. The excerpt must itself state the rule or the answer. It is not "
    "enough that it concerns the same topic, uses the same keywords, or "
    "resembles the answer. The excerpt must be an exact substring of one of "
    "the five TextUnits.\n"
    "- UNCERTAIN: the material concerns the question's topic but does not "
    "answer it with certainty. Use this when the excerpts are only nearby "
    "(for example a narrow exception or a sanction instead of a general "
    "rule), when they disagree, or when there are only headings or references "
    "without the rule itself.\n"
    "- NOT_FOUND: none of the excerpts concern the question's topic at all."
)

P0_V2_EN_DECISION = (
    "\n\nDecision:\n"
    "1. Does an excerpt itself answer the question? Then ANSWERED.\n"
    "2. Otherwise: does any excerpt concern the topic? Then UNCERTAIN.\n"
    "3. Otherwise: NOT_FOUND.\n\n"
    "If several excerpts are relevant, choose the one that itself states the "
    "rule, not the one that refers to it or surrounds it.\n"
    "A nearby excerpt is never ANSWERED."
)

P0_V2_CRITERIA = {
    ANSWERED: "Ett utdrag besvarar frågan direkt och uttrycker själv regeln.",
    UNCERTAIN: "Ämnet berörs men inget utdrag besvarar frågan säkert.",
    NOT_FOUND: "Inget utdrag rör frågans ämne.",
}

P0_V2_EN_CRITERIA = {
    ANSWERED: "An excerpt answers the question directly and itself states the rule.",
    UNCERTAIN: "The topic is touched but no excerpt answers the question with certainty.",
    NOT_FOUND: "No excerpt concerns the question's topic.",
}

SHARP_QUESTIONS = {
    "auto-renewal": (
        "Förlängs avtalet automatiskt med en ny period om det inte sägs upp? "
        "Räknas inte: att avtalet gäller tills vidare, eller att det kan "
        "förlängas efter ny överenskommelse."
    ),
    "notice-period": (
        "Vilken uppsägningstid gäller för avtalet i sin helhet? "
        "Räknas inte: uppsägning vid avtalsbrott, hävning, eller uppsägning "
        "av ett tilläggsavtal."
    ),
    "liability-cap": (
        "Sätter avtalet ett tak för, eller utesluter, en parts skadeståndsansvar? "
        "Räknas inte: vite, straffavgift eller annan avtalad sanktion. "
        "Räknas inte: friskrivning för en enskild skadetyp eller händelse."
    ),
    "confidentiality": (
        "Förpliktar avtalet en part att hålla information hemlig "
        "(tystnadsplikt eller sekretessplikt)? "
        "Räknas inte: att avtalets eget innehåll är konfidentiellt."
    ),
    "liability-secrecy-carveout": (
        "Undantas brott mot sekretess från en generell ansvarsbegränsning? "
        "Räknas inte: undantag från en slutlig uppgörelse, från vite, eller "
        "att sekretessbrott ger skadestånd."
    ),
}

SHARP_QUESTIONS_EN = {
    "auto-renewal": (
        "Does the agreement renew automatically for a new period unless notice "
        "is given? Does not count: that the agreement continues until further "
        "notice, or that it may be extended by a new agreement."
    ),
    "notice-period": (
        "What notice period applies to the agreement as a whole? "
        "Does not count: termination for breach, cancellation, or notice for "
        "an addendum only."
    ),
    "liability-cap": (
        "Does the agreement cap or exclude a party's liability for damages? "
        "Does not count: liquidated damages, a penalty, or another agreed "
        "sanction. Does not count: a disclaimer for a single type of loss or event."
    ),
    "confidentiality": (
        "Does the agreement require a party to keep information secret "
        "(a duty of confidentiality or non-disclosure)? "
        "Does not count: that the agreement's own contents are confidential."
    ),
    "liability-secrecy-carveout": (
        "Is a breach of confidentiality carved out from a general liability "
        "limitation? Does not count: an exception from a settlement, from "
        "liquidated damages, or that a secrecy breach gives rise to damages."
    ),
}

INSTRUCTIONS[PROMPT_P0_V2_B] = P0_V2_DEFINITIONS
INSTRUCTIONS[PROMPT_P0_V2] = P0_V2_DEFINITIONS + P0_V2_DECISION
INSTRUCTIONS[PROMPT_P0_V2_D] = P0_V2_DEFINITIONS + P0_V2_DECISION
INSTRUCTIONS[PROMPT_P0_V2_EN] = P0_V2_EN_DEFINITIONS + P0_V2_EN_DECISION

HYPOTHESES[PROMPT_P0_V2_B] = "New status definitions only."
HYPOTHESES[PROMPT_P0_V2] = "Definitions plus decision tree."
HYPOTHESES[PROMPT_P0_V2_D] = "Decision tree plus sharper questions."
HYPOTHESES[PROMPT_P0_V2_EN] = "English P0_v2 with sharper questions."


def instruction_for(prompt_id: str) -> str:
    if prompt_id not in INSTRUCTIONS:
        raise ValueError(f"unsupported answer prompt: {prompt_id}")
    return INSTRUCTIONS[prompt_id]


def criteria_for(prompt_id: str) -> dict[str, str]:
    if prompt_id == PROMPT_P0_V2_EN:
        return dict(P0_V2_EN_CRITERIA)
    if prompt_id in {PROMPT_P0_V2_B, PROMPT_P0_V2, PROMPT_P0_V2_D}:
        return dict(P0_V2_CRITERIA)
    return dict(P0_STATUS_CRITERIA)


def questions_for(prompt_id: str) -> dict[str, str]:
    if prompt_id == PROMPT_P0_V2_D:
        return dict(SHARP_QUESTIONS)
    if prompt_id == PROMPT_P0_V2_EN:
        return dict(SHARP_QUESTIONS_EN)
    return dict(USER_QUESTIONS)
