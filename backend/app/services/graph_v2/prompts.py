"""Runtime semantic decision text seeded into prompt_fields."""

import json

from app.services.graph_v2.result_prompts import result_reuse_prompt_fields


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
    node_question = {
        "type": "choice",
        "instructions": (
            "Compare two typed value or concept nodes. Choose SAME only when they "
            "refer to the same concept under the given value_type, even if their "
            "wording differs. Otherwise choose DISTINCT. Do not infer new facts."
        ),
        "criteria": {"SAME": "Equivalent concept or value.",
                     "DISTINCT": "Different or uncertain concept or value."},
    }
    node_field = {
        "key": "research.graph_node_resolution", "section": "research",
        "label": {"sv": "Graf — nodupplösning", "en": "Graph — node resolution"},
        "hint": {"sv": "Semantisk jämförelse av värden.",
                 "en": "Semantic comparison of values."},
        "defaults": {"sv": json.dumps(node_question), "en": json.dumps(node_question)},
    }
    return [field, legal_report_field, node_field,
            {**node_field, "key": "rattsunderlag.graph_node_resolution"}, *result_reuse_prompt_fields()]
