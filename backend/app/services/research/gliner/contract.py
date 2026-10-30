"""Frozen E1–E3 span-contract rules for the optional GLiNER2 span proposer.

Ported from the swe-gym experiments (blindtest v1 + E1 span-date-v1 + E2
canonical values + E3 operational roles; PRs #443–#446). These are control
decisions, not LLM prompts: the module derives VERIFIED / AMBIGUOUS /
REJECTED from Jev verdicts and observable span properties. No gold, no
facit, no learned policy. Rules are data so they stay reviewable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Frozen span-type vocabulary. A ResearchNeed may only declare these types.
SPAN_TYPES = frozenset(
    {
        "NOTICE_PERIOD",
        "SEVERANCE",
        "SEVERANCE_VALUE",
        "TERMINATION_CONDITION",
        "RENEWAL",
        "PENALTY",
        "LIABILITY_CAP",
        "EXCEPTION",
        "PARTY",
        "MONEY",
        "DATE",
        "PERIOD",
    }
)

#: Frozen Swedish labels GLiNER2 is asked with (need-driven, never automatic).
NEED_LABELS = {
    "NOTICE_PERIOD": "Uppsägningstid",
    "SEVERANCE": "Avgångsvederlag",
    "SEVERANCE_VALUE": "Ersättning",
    "TERMINATION_CONDITION": "Uppsägningsvillkor",
    "RENEWAL": "Förlängning",
    "PENALTY": "Vite",
    "LIABILITY_CAP": "Ansvarstak",
    "EXCEPTION": "Undantag",
    "PARTY": "Avtalspart",
    "MONEY": "Belopp",
    "DATE": "Datum",
    "PERIOD": "Tidsperiod",
}

#: Frozen contrast rules per concept class (JEV arm D), not per golden case.
CONTRASTS = {
    "Uppsägningstid": "En uppsägningstid är inte samma sak som avtalstid, förlängningsperiod eller betalningsfrist.",
    "Avgångsvederlag": "Ett avgångsvederlag är inte samma sak som lön, pension eller skadestånd.",
    "Ersättning": "En ersättningsrätt är inte samma sak som lön, arvode eller skadestånd.",
    "Uppsägningsvillkor": "Ett uppsägningsvillkor är inte samma sak som uppsägningstid, avtalstid eller partsbeskrivning.",
    "Förlängning": "En förlängningsperiod är inte samma sak som uppsägningstid, avtalstid eller betalningsfrist.",
    "Vite": "Ett vite är inte samma sak som pris, avgift eller skadestånd.",
    "Ansvarstak": "Ett ansvarstak är inte samma sak som vite, garanti eller försäkringsskydd.",
    "Undantag": "Ett undantag är inte samma sak som en skyldighet, en definition eller en hänvisning.",
    "Avtalspart": "En avtalspart är inte samma sak som en roll, en titel eller en adress.",
    "Belopp": "Ett belopp är inte samma sak som ett datum, en procentsats eller ett antal.",
    "Datum": "Ett datum är inte samma sak som en tidsperiod, en tidsfrist eller en ålder.",
    "Tidsperiod": "En tidsperiod är inte samma sak som ett datum, en tidsfrist eller en ålder.",
}

#: Frozen JEV prompt versions.
ARM_D_VERSION = "span-need-contrast-v1"
DATE_VERSION = "span-date-v1"

#: Frozen operational-role vocabulary (E3). A need may declare one role.
ROLES = frozenset(
    {"NOTICE", "DURATION", "DEADLINE", "MONEY", "PARTY", "LIABILITY", "SEMESTER", "EVENT"}
)

#: Closed list of leading grammatical words stripped by canonical-value
#: normalization. Quantifiers (minst/högst/cirka) are deliberately NOT here —
#: they carry semantic load.
LEADING_WORDS = frozenset({"inom", "i", "under", "senast", "den", "det", "de", "en", "ett"})

#: Unit genitive normalization (E2).
GENITIVE_UNITS = {
    "dagars": "dagar",
    "veckors": "veckor",
    "månaders": "månader",
    "års": "år",
    "timmars": "timmar",
}

#: Closed role-cue vocabulary (E3). A span gets the role of the nearest cue.
ROLE_CUES = {
    "NOTICE": ["uppsägningstid", "uppsägning", "varsel", "frånträda", "upphöra"],
    "DURATION": ["gäller", "löper", "längd", "avtalstid"],
    "DEADLINE": ["inom", "senast", "efter", "betalning", "betalningsvillkor", "faktura",
                 "fakturan", "frist", "tillhanda", "erläggs", "förfallodatum",
                 "utbetalning", "utbetala"],
    "MONEY": ["belopp", "kr", "arvode", "arvodet", "ersättning", "pris", "timpris",
              "lön", "garanterar", "betalar", "sponsorbidrag", "procent"],
    "PARTY": ["benämnd", "kallas", "parter", "mellan", "aktiebolag", "klubb", "ab"],
    "LIABILITY": ["ansvar", "begränsat", "begräns"],
    "SEMESTER": ["semester"],
    "EVENT": ["startdatum", "tillträdesdag", "simning", "exponerad", "nuss"],
}

REJECTED = "REJECTED"
VERIFIED = "VERIFIED"
AMBIGUOUS = "AMBIGUOUS"


def canon(s: str) -> str:
    """Frozen canonical span form: brackets removed, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[\[\]]", "", s)).strip().lower()


def despace(s: str) -> str:
    """All whitespace removed — robust against extraction whitespace artifacts."""
    return re.sub(r"\s+", "", canon(s))


def canon_value(s: str) -> str:
    """Frozen canonical value (E2): leading grammatical words stripped,
    unit genitives normalized. Never merges distinct operational roles."""
    words = canon(s).split()
    while words and words[0] in LEADING_WORDS:
        words = words[1:]
    words = [GENITIVE_UNITS.get(w, w) for w in words]
    return " ".join(words)


def arm_d_instructions(need_type: str, span: str) -> str:
    need = NEED_LABELS.get(need_type, need_type)
    return (
        f"Utgör det exakta spannet '{span}' ett {need} för det angivna avtalet? "
        f"{CONTRASTS.get(need, 'Bedöm enbart spannet.')}"
    )


def span_date_instructions(span: str) -> str:
    return (
        f"Utgör det exakta spannet '{span}' ett datum eller ett datumintervall — "
        "även utan årtal, som '12 maj' eller '10-11 juni'? Bedöm enbart spannet. "
        "Lägg inte till ett årtal som inte står i spannet."
    )


def verification_question(need_type: str, span: str) -> dict[str, object]:
    """The frozen Jev control question for one proposed span."""
    if need_type == "DATE":
        version = DATE_VERSION
        instructions = span_date_instructions(span)
    else:
        version = ARM_D_VERSION
        instructions = arm_d_instructions(need_type, span)
    return {
        "prompt_version": version,
        "question": {
            "evidence": {
                "type": "choice",
                "instructions": instructions,
                "criteria": {
                    "YES": "Spannet utgör exakt det efterfrågade sakförhållandet.",
                    "NO": "Spannet utgör inte det efterfrågade sakförhållandet.",
                    "UNCERTAIN": "Går inte att avgöra.",
                },
            }
        },
    }


def operational_role(span: str, unit_text: str) -> str | None:
    """Frozen closest-role-cue rule (E3).

    Cues are matched on the de-spaced text (robust against whitespace
    artifacts) but must satisfy word boundaries in the original text, so
    'senast' never matches inside 'senaste'. The role of the cue with the
    minimal character distance to the span wins; a tie between two different
    roles returns None (undeterminable — treated as competing downstream).
    """
    ctext = despace(unit_text)
    otext = canon(unit_text)
    index_map: list[int] = []
    for position, char in enumerate(otext):
        if not char.isspace():
            index_map.append(position)
    sval = despace(span)
    pos = ctext.find(sval)
    if pos < 0:
        return None
    span_end = pos + len(sval)
    best_role: str | None = None
    best_dist: int | None = None
    for role, words in ROLE_CUES.items():
        for word in words:
            needle = despace(word)
            idx = ctext.find(needle)
            while idx >= 0:
                begin = index_map[idx] if idx < len(index_map) else len(otext)
                last = idx + len(needle) - 1
                end = index_map[last] + 1 if last < len(index_map) else len(otext)
                before_ok = begin == 0 or not otext[begin - 1].isalnum()
                after_ok = end >= len(otext) or not otext[end].isalnum()
                if before_ok and after_ok:
                    dist = max(pos - (idx + len(needle)), idx - span_end, 0)
                    if best_dist is None or dist < best_dist:
                        best_role, best_dist = role, dist
                    elif dist == best_dist and role != best_role:
                        return None
                idx = ctext.find(needle, idx + 1)
    return best_role


@dataclass(frozen=True)
class SpanVerdict:
    """One frozen Jev answer for one proposed span."""

    span: str
    need_type: str
    prompt_version: str
    choice: str  # YES / NO / UNCERTAIN
    unit_id: str = ""
    unit_text: str = ""


@dataclass(frozen=True)
class ContractFinding:
    """One span's contract state for a need."""

    span: str
    value: str
    need_type: str
    state: str  # VERIFIED / AMBIGUOUS / REJECTED
    role: str | None = None
    prompt_version: str = ""
    unit_id: str = ""
    choice: str = ""


@dataclass(frozen=True)
class NeedFindings:
    need_id: str
    findings: tuple[ContractFinding, ...] = field(default_factory=tuple)

    def verified_values(self) -> tuple[str, ...]:
        return tuple(
            finding.value for finding in self.findings if finding.state == VERIFIED
        )


def derive_findings(
    verdicts: list[SpanVerdict],
    *,
    need_type: str,
    need_role: str,
) -> list[ContractFinding]:
    """Frozen contract over ALL units' verdicts for one need.

    - REJECTED: Jev answered NO or UNCERTAIN.
    - A Jev YES alone never makes a finding usable: the type question was
      need-specific, but the value must also be unambiguous for the need's
      operational role (E3) across every scanned unit.
    - AMBIGUOUS: two or more distinct canonical values compete for the same
      operational role — aggregated across units, not per unit. A span whose
      role cannot be determined always counts as competing, and a span with a
      determinable different role neither competes nor belongs to this need.
    - Without a declared need role, every YES span counts as competing
      (fail-safe default, pre-E3 strictness).
    """
    approved = [v for v in verdicts if v.choice == "YES"]
    findings: list[ContractFinding] = []
    for verdict in verdicts:
        if verdict.choice != "YES":
            findings.append(
                ContractFinding(
                    span=verdict.span,
                    value=canon_value(verdict.span),
                    need_type=need_type,
                    state=REJECTED,
                    prompt_version=verdict.prompt_version,
                    unit_id=verdict.unit_id,
                    choice=verdict.choice,
                )
            )
    if not approved:
        return findings
    # The role belongs to the verdict IN ITS UNIT: the same span text can be
    # a notice period in one TextUnit and a payment deadline in another, so
    # roles are index-aligned with verdicts — never keyed by span text.
    roles = [operational_role(verdict.span, verdict.unit_text) for verdict in approved]
    # E3: a span with a determinable role that differs from the need's role
    # is another operational fact — it neither competes nor belongs to this
    # need's findings. Undeterminable roles always compete (fail-safe).
    relevant = [
        (verdict, role)
        for verdict, role in zip(approved, roles, strict=True)
        if not need_role or role is None or role == need_role
    ]
    distinct_values = {canon_value(verdict.span) for verdict, _role in relevant}
    ambiguous_values = distinct_values if len(distinct_values) >= 2 else set()
    for verdict, role in relevant:
        value = canon_value(verdict.span)
        state = AMBIGUOUS if value in ambiguous_values else VERIFIED
        findings.append(
            ContractFinding(
                span=verdict.span,
                value=value,
                need_type=need_type,
                state=state,
                role=role,
                prompt_version=verdict.prompt_version,
                unit_id=verdict.unit_id,
                choice=verdict.choice,
            )
        )
    return findings
