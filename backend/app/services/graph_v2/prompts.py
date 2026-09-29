"""Runtime semantic decision text seeded into prompt_fields."""

import json


def graph_fact_prompt_fields() -> list[dict]:
    question = {
        "type": "choice",
        "instructions": (
            "Compare the two complete fact assertions in the state. Their subject, "
            "relation, target, context and historical occurrence already match. "
            "Choose SAME only if both assert the same proposition, CONTRADICTS only "
            "if they cannot both be true at the same valid time, otherwise DISTINCT. "
            "A contradiction does not itself revoke a prior fact."
        ),
        "criteria": {
            "SAME": "Logically equivalent assertion.",
            "DISTINCT": "Additional detail, different claim or unresolved ambiguity.",
            "CONTRADICTS": "Mutually exclusive assertions for the same occurrence and time.",
        },
    }
    field = {
        "key": "research.graph_fact_resolution",
        "section": "research",
        "label": {"sv": "Graf — faktaupplösning", "en": "Graph — fact resolution"},
        "hint": {"sv": "Semantisk jämförelse av faktakanter.",
                 "en": "Semantic comparison of fact edges."},
        "defaults": {"sv": json.dumps(question), "en": json.dumps(question)},
    }
    legal_report_field = {
        **field,
        "key": "rattsunderlag.graph_fact_resolution",
    }
    return [field, legal_report_field]
