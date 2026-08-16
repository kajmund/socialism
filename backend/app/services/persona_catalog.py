"""Shared Swedish name/district/job catalogs for stub + LLM slot sampling."""

NAMES_F = ["Margareta", "Eva", "Linnéa", "Birgitta", "Karin", "Amanda", "Yasmin", "Ingrid"]
NAMES_M = ["Bengt", "Erik", "Mikael", "Hassan", "Sven", "Johan", "Kalle", "Anders"]
LASTN = [
    "Hellström",
    "Karlsson",
    "Berg",
    "Lindqvist",
    "Andersson",
    "Svensson",
    "Nilsson",
    "Al-Amin",
]
JOB_BY_CAT: dict[str, str] = {
    "vard": "Undersköterska",
    "industri": "Lagerarbetare",
    "utbildning": "Lärare",
    "handel": "Butiksbiträde",
    "tjansteman": "Handläggare",
    "ovrigt": "Pensionär",
}
DISTRICT_LABEL: dict[str, str] = {
    "hageby": "Distrikt A",
    "navestad": "Distrikt B",
    "lindo": "Distrikt C",
    "klockaretorpet": "Distrikt D",
    "centrum": "Centrum",
    "ovriga": "Övriga",
}
LEAN_LABEL: dict[str, str] = {
    "vanster": "Vänster",
    "mvanster": "Mitt-vänster",
    "mitt": "Mitt",
    "mhoger": "Mitt-höger",
    "hoger": "Höger",
}
