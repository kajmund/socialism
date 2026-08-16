"""Default grunddata option lists for persona composer dropdowns."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class GeoBoundsDict(TypedDict):
    south: float
    west: float
    north: float
    east: float


class CatalogItemDict(TypedDict):
    label: str
    description: NotRequired[str]
    bounds: NotRequired[GeoBoundsDict | None]


class CatalogDefault(TypedDict):
    key: str
    section: str
    title: str
    items: list[CatalogItemDict]


# Approximate district footprints for relative geography + heatmap scaffolding.
_ORT_ITEMS: list[CatalogItemDict] = [
    {
        "label": "Distrikt A",
        "description": (
            "Bostadsområde med miljonprogramskaraktär söder om centrum: "
            "flerfamiljshus, lokal service och återkommande frågor om trygghet, "
            "skola och renovering."
        ),
        "bounds": {
            "south": 58.5680,
            "west": 16.1700,
            "north": 58.5800,
            "east": 16.1950,
        },
    },
    {
        "label": "Distrikt B",
        "description": (
            "Bostadsområde med blandad bebyggelse sydost om centrum, "
            "liknande A i miljonprogramsprofil men egen lokal identitet och service."
        ),
        "bounds": {
            "south": 58.5680,
            "west": 16.1950,
            "north": 58.5800,
            "east": 16.2200,
        },
    },
    {
        "label": "Distrikt C",
        "description": (
            "Villa- och radhusområde nordost om centrum: mer småhusprägel, "
            "högre bilberoende och oftare fokus på skola, trafik och trygghet i grannskapet."
        ),
        "bounds": {
            "south": 58.5950,
            "west": 16.1950,
            "north": 58.6080,
            "east": 16.2200,
        },
    },
    {
        "label": "Distrikt D",
        "description": (
            "Villa-/radhuspräglat område nordväst om centrum med blandad hushållsinkomst; "
            "vardagsfrågor kring skola, kollektivtrafik och lokal service."
        ),
        "bounds": {
            "south": 58.5950,
            "west": 16.1550,
            "north": 58.6080,
            "east": 16.1800,
        },
    },
    {
        "label": "Centrum",
        "description": (
            "Handel, kontor och äldre stenstad kring innerstaden: blandad hushållsinkomst, "
            "tät service, parkering/trafik och stadsliv präglar vardagen."
        ),
        "bounds": {
            "south": 58.5820,
            "west": 16.1750,
            "north": 58.5940,
            "east": 16.2000,
        },
    },
    {
        "label": "Övriga",
        "description": (
            "Ytterområden och mindre orter i kommunen utanför de namngivna distrikten; "
            "mer gles bebyggelse och längre till central service."
        ),
        "bounds": {
            "south": 58.5450,
            "west": 16.1400,
            "north": 58.5650,
            "east": 16.2500,
        },
    },
]


def _labels(*labels: str) -> list[CatalogItemDict]:
    return [{"label": label} for label in labels]


CATALOG_DEFAULTS: list[CatalogDefault] = [
    {
        "key": "kön",
        "section": "demografi",
        "title": "Kön",
        "items": _labels("Kvinna", "Man", "Icke-binär"),
    },
    {
        "key": "yrke",
        "section": "demografi",
        "title": "Yrken",
        "items": _labels(
            "Undersköterska",
            "Lagerarbetare",
            "Grundskollärare",
            "Taxichaufför",
            "Barnmorska",
            "Handläggare",
            "Butiksbiträde",
            "Egen företagare",
        ),
    },
    {
        "key": "utbildning",
        "section": "demografi",
        "title": "Utbildningsnivåer",
        "items": _labels("Grundskola", "Gymnasium", "Högskola"),
    },
    {
        "key": "livssituation",
        "section": "demografi",
        "title": "Livssituationer",
        "items": _labels(
            "Ensamhushåll",
            "Sambo, barn",
            "Bor med föräldrar",
            "Gift, vuxna barn",
            "Sambo, inga barn",
        ),
    },
    {
        "key": "ort",
        "section": "demografi",
        "title": "Distrikt",
        "items": _ORT_ITEMS,
    },
    {
        "key": "parti",
        "section": "politik",
        "title": "Partisympatier",
        "items": _labels(
            "Vänsterpartiet",
            "Socialdemokraterna",
            "Miljöpartiet",
            "Centerpartiet",
            "Liberalerna",
            "Moderaterna",
            "Kristdemokraterna",
            "Sverigedemokraterna",
            "Osäker väljare",
        ),
    },
    {
        "key": "lutning",
        "section": "politik",
        "title": "Politisk lutning",
        "items": _labels("Vänster", "Mitt-vänster", "Mitt", "Mitt-höger", "Höger"),
    },
    {
        "key": "valdeltagande",
        "section": "politik",
        "title": "Valdeltagande",
        "items": _labels("Röstar alltid", "Röstar oftast", "Osäker om hen röstar"),
    },
    {
        "key": "sakfragor",
        "section": "varderingar",
        "title": "Sakfrågor",
        "items": _labels(
            "Vård och skola",
            "Bostäder och trygghet",
            "Ekonomi och jobb",
            "Miljö och klimat",
        ),
    },
    {
        "key": "fortroende",
        "section": "varderingar",
        "title": "Förtroende",
        "items": _labels(
            "Högt för kommunen",
            "Högt för sjukvården",
            "Blandat",
            "Litar på lokala politiker",
            "Lågt för kommunen",
            "Skeptisk mot politiker generellt",
        ),
    },
    {
        "key": "ton",
        "section": "rost_media",
        "title": "Ton",
        "items": _labels(
            "Optimistisk och pratglad",
            "Varm men bestämd",
            "Saklig och nyanserad",
            "Direkt och kort i tonen",
            "Eftertänksam, gärna med frågor",
            "Sarkastisk och otålig",
            "Cynisk mot politiker",
        ),
    },
    {
        "key": "sprak",
        "section": "rost_media",
        "title": "Språkmönster",
        "items": _labels(
            "Kort och konkret",
            "Långa resonemang",
            "Blandar in fackspråk",
            "Vardagligt, många skämt",
        ),
    },
    {
        "key": "medievanor",
        "section": "rost_media",
        "title": "Medievanor",
        "items": _labels(
            "Instagram, FB-grupper",
            "Lokal nyhetskälla",
            "Regional TV",
            "Lite/ingen media",
        ),
    },
    {
        "key": "avsandare",
        "section": "simulering",
        "title": "Avsändare",
        "items": _labels(
            "Socialdemokraterna",
            "Moderaterna",
            "Centerpartiet",
            "Lokalnyheterna",
            "Lokaltidningen",
            "@partihandle",
        ),
    },
]

# Unmodified seed lists from before the balanced ton/förtroende defaults.
# ensure_catalog_defaults replaces an exact match so existing configs pick up
# the new lists; operator-edited lists are left alone.
PREVIOUS_STOCK_LABELS: dict[str, frozenset[str]] = {
    "ton": frozenset(
        {
            "Sarkastisk och otålig",
            "Uppgiven men engagerad",
            "Optimistisk och pratglad",
            "Direkt och kort i tonen",
            "Cynisk mot politiker",
        }
    ),
    "fortroende": frozenset(
        {
            "Lågt för kommunen",
            "Högt för sjukvården",
            "Blandat, skeptisk generellt",
            "Lågt för kommunen / Högt för sjukvården",
        }
    ),
}

SECTION_ORDER = ("demografi", "politik", "varderingar", "rost_media", "simulering")

SECTION_LABELS: dict[str, str] = {
    "demografi": "Demografi",
    "politik": "Politik",
    "varderingar": "Värderingar",
    "rost_media": "Röst & media",
    "simulering": "Simulering",
}

ORT_DEFAULTS_BY_LABEL: dict[str, CatalogItemDict] = {
    item["label"]: item for item in _ORT_ITEMS
}
