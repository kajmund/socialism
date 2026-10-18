"""Group-voice prompt defaults seeded into the catalog."""

from __future__ import annotations


def group_voice_prompt_fields() -> list[dict]:
    return [
        {
            "key": "sme.group_voice.keep_hand",
            "section": "panel",
            "label": {"sv": "Gruppröst — behåll hand", "en": "Group voice — keep hand"},
            "hint": {
                "sv": "Jev-bedömning om en expert ska behålla sin hand. Platshållare: {name}",
                "en": "Jev judgment whether an expert should keep their hand. Placeholder: {name}",
            },
            "defaults": {
                "sv": (
                    "Är poängen {name} ville ta upp fortfarande relevant och obesvarad "
                    "givet den senaste diskussionen? Svara ja om handen ska vara kvar."
                ),
                "en": (
                    "Is the point {name} wanted to raise still relevant and unanswered "
                    "given the recent discussion? Answer yes if the hand should stay raised."
                ),
                "nb": (
                    "Är poängen {name} ville ta upp fortfarande relevant och obesvarad "
                    "givet den senaste diskussionen? Svara ja om handen ska vara kvar."
                ),
            },
        },
        {
            "key": "sme.group_voice.raise_hand",
            "section": "panel",
            "label": {"sv": "Gruppröst — räck upp handen", "en": "Group voice — raise hand"},
            "hint": {
                "sv": "Jev-bedömning om en expert vill säga något. Platshållare: {name}",
                "en": "Jev judgment whether an expert wants to speak. Placeholder: {name}",
            },
            "defaults": {
                "sv": (
                    "Har {name} en egen poäng att lägga till efter det som just sades? "
                    "Svara ja bara om personen bör få ordet. Svara nej om det räcker att lyssna."
                ),
                "en": (
                    "Does {name} have a distinct point to add after what was just said? "
                    "Answer yes only if they should speak. Answer no if listening is enough."
                ),
                "nb": (
                    "Har {name} en egen poäng att lägga till efter det som just sades? "
                    "Svara ja bara om personen bör få ordet. Svara nej om det räcker att lyssna."
                ),
            },
        },
    ]
