"""Database-owned Jev prompts for bounded answer reuse and graph navigation."""

import json


def result_reuse_prompt_fields() -> list[dict]:
    labels = {
        "research.result_navigation": {
            "sv": "Närliggande researchfrågor",
            "en": "Related research questions",
        },
        "research.result_coverage": {"sv": "Sparade svars täckning", "en": "Saved answer coverage"},
    }
    definitions = {
        "research.result_navigation": {
            "type": "noul",
            "instructions": "For the indicated edge, could following it to the neighbour help answer the requested question in its context? Assess only this edge, not the entire branch or graph.",
            "criteria": {
                "true": "The neighbour may contain relevant answers or lead to them; uncertainty warrants exploration.",
                "false": "This relation and neighbour are clearly unrelated to the requested question.",
            },
        },
        "research.result_coverage": {
            "type": "choice",
            "instructions": "The saved question already has a sufficient, temporally valid frozen research basis. Does that saved question fully encompass the requested question in its requested context? Do not infer coverage of additional aspects from topic similarity. Compare scope, time, conditions, source constraints and contradictions. Similar wording is insufficient. FULL requires explicit support for every material aspect; choose PARTIAL for useful but incomplete support and NONE for irrelevant or uncertain support.",
            "criteria": {
                "FULL": "Complete supported coverage of the requested question and context, without material contradiction or missing aspect.",
                "PARTIAL": "Relevant support exists but additional research is required.",
                "NONE": "Irrelevant evidence or coverage cannot be established.",
            },
        },
    }
    return [
        {
            "key": key,
            "section": "research",
            "label": labels[key],
            "hint": {"sv": "Återanvändning av färdig research.", "en": "Completed research reuse."},
            "defaults": {language: json.dumps(question) for language in ("sv", "en")},
        }
        for key, question in definitions.items()
    ]
