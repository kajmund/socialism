"""Default grunddata option lists for persona composer dropdowns."""

from __future__ import annotations

from typing import TypedDict


class CatalogDefault(TypedDict):
    key: str
    section: str
    title: str
    items: list[str]


CATALOG_DEFAULTS: list[CatalogDefault] = [
    {
        "key": "yrke",
        "section": "demografi",
        "title": "Yrken",
        "items": [
            "Undersköterska",
            "Lagerarbetare",
            "Grundskollärare",
            "Taxichaufför",
            "Barnmorska",
            "Handläggare",
            "Butiksbiträde",
            "Egen företagare",
        ],
    },
    {
        "key": "utbildning",
        "section": "demografi",
        "title": "Utbildningsnivåer",
        "items": ["Grundskola", "Gymnasium", "Högskola"],
    },
    {
        "key": "livssituation",
        "section": "demografi",
        "title": "Livssituationer",
        "items": [
            "Ensamhushåll",
            "Sambo, barn",
            "Bor med föräldrar",
            "Gift, vuxna barn",
            "Sambo, inga barn",
        ],
    },
    {
        "key": "ort",
        "section": "demografi",
        "title": "Orter / stadsdelar",
        "items": [
            "Distrikt A",
            "Distrikt B",
            "Distrikt C",
            "Distrikt D",
            "Centrum",
            "Övriga",
        ],
    },
    {
        "key": "parti",
        "section": "politik",
        "title": "Partisympatier",
        "items": [
            "Vänsterpartiet",
            "Socialdemokraterna",
            "Miljöpartiet",
            "Centerpartiet",
            "Liberalerna",
            "Moderaterna",
            "Kristdemokraterna",
            "Sverigedemokraterna",
            "Osäker väljare",
        ],
    },
    {
        "key": "lutning",
        "section": "politik",
        "title": "Politisk lutning",
        "items": ["Vänster", "Mitt-vänster", "Mitt", "Mitt-höger", "Höger"],
    },
    {
        "key": "valdeltagande",
        "section": "politik",
        "title": "Valdeltagande",
        "items": ["Röstar alltid", "Röstar oftast", "Osäker om hen röstar"],
    },
    {
        "key": "sakfragor",
        "section": "varderingar",
        "title": "Sakfrågor",
        "items": [
            "Vård och skola",
            "Bostäder och trygghet",
            "Ekonomi och jobb",
            "Miljö och klimat",
        ],
    },
    {
        "key": "fortroende",
        "section": "varderingar",
        "title": "Förtroende",
        "items": [
            "Lågt för kommunen",
            "Högt för sjukvården",
            "Blandat, skeptisk generellt",
            "Lågt för kommunen / Högt för sjukvården",
        ],
    },
    {
        "key": "ton",
        "section": "rost_media",
        "title": "Ton",
        "items": [
            "Sarkastisk och otålig",
            "Uppgiven men engagerad",
            "Optimistisk och pratglad",
            "Direkt och kort i tonen",
            "Cynisk mot politiker",
        ],
    },
    {
        "key": "sprak",
        "section": "rost_media",
        "title": "Språkmönster",
        "items": [
            "Kort och konkret",
            "Långa resonemang",
            "Blandar in fackspråk",
            "Vardagligt, många skämt",
        ],
    },
    {
        "key": "medievanor",
        "section": "rost_media",
        "title": "Medievanor",
        "items": [
            "Instagram, FB-grupper",
            "Lokal nyhetskälla",
            "Regional TV",
            "Lite/ingen media",
        ],
    },
]

SECTION_ORDER = ("demografi", "politik", "varderingar", "rost_media")

SECTION_LABELS: dict[str, str] = {
    "demografi": "Demografi",
    "politik": "Politik",
    "varderingar": "Värderingar",
    "rost_media": "Röst & media",
}
