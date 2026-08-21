"""Shared Swedish name/district/job catalogs for stub + LLM slot sampling."""

from __future__ import annotations

from datetime import date
from random import Random

from app.services.persona_catalog_scb_names import (
    DECADES,
    FIRST_NAMES_BY_DECADE_F,
    FIRST_NAMES_BY_DECADE_M,
    SCB_LASTN,
)

_KON_FEMALE = "Kvinna"
_KON_MALE = "Man"

# Flat fallback pools when age is unknown or outside SCB decade coverage.
NAMES_F = [
    "Margareta",
    "Eva",
    "Linnéa",
    "Birgitta",
    "Karin",
    "Amanda",
    "Yasmin",
    "Ingrid",
    "Anna",
    "Maria",
    "Kristina",
    "Elisabeth",
    "Sofia",
    "Emma",
    "Sara",
    "Linda",
    "Jenny",
    "Helena",
    "Susanne",
    "Monica",
    "Annika",
    "Camilla",
    "Malin",
    "Johanna",
    "Rebecca",
    "Frida",
    "Elin",
    "Ida",
    "Maja",
    "Klara",
    "Agnes",
    "Vera",
    "Ella",
    "Wilma",
    "Alva",
    "Ebba",
    "Alicia",
    "Felicia",
    "Jessica",
    "Sandra",
    "Petra",
    "Ulrika",
    "Carina",
    "Lena",
    "Pernilla",
    "Åsa",
    "Gunilla",
    "Viveca",
    "Cecilia",
    "Therese",
    "Caroline",
    "Emilia",
    "Matilda",
    "Isabelle",
    "Josefin",
    "Hanna",
    "Louise",
    "Viktoria",
    "Madeleine",
    "Anette",
    "Kerstin",
    "Ulla",
    "Barbro",
    "Inger",
    "Marianne",
    "Solveig",
    "Astrid",
    "Elsa",
    "Sigrid",
    "Gunnel",
    "Irene",
    "Sonja",
    "Anita",
    "Lotta",
    "Ronja",
    "Selma",
    "Moa",
    "Tuva",
    "Meja",
    "Tyra",
    "Viola",
    "Berit",
    "Doris",
]
NAMES_M = [
    "Bengt",
    "Erik",
    "Mikael",
    "Hassan",
    "Sven",
    "Johan",
    "Kalle",
    "Anders",
    "Lars",
    "Karl",
    "Nils",
    "Per",
    "Jan",
    "Peter",
    "Thomas",
    "Magnus",
    "Fredrik",
    "Daniel",
    "Stefan",
    "Martin",
    "Andreas",
    "Mattias",
    "Jonas",
    "Henrik",
    "Patrik",
    "Marcus",
    "Oscar",
    "Viktor",
    "Alexander",
    "William",
    "Lucas",
    "Oliver",
    "Hugo",
    "Liam",
    "Elias",
    "Axel",
    "Gustav",
    "Filip",
    "Emil",
    "Anton",
    "Simon",
    "Sebastian",
    "Adrian",
    "Kevin",
    "Robin",
    "Jonathan",
    "Tobias",
    "Niklas",
    "Christoffer",
    "Joakim",
    "Pontus",
    "Oskar",
    "Rasmus",
    "Felix",
    "Albin",
    "Ludvig",
    "Melvin",
    "Vincent",
    "Arvid",
    "Theo",
    "Leo",
    "Max",
    "Göran",
    "Ulf",
    "Lennart",
    "Bertil",
    "Rolf",
    "Stig",
    "Arne",
    "Leif",
    "Kent",
    "Roger",
    "Tommy",
    "Mohamed",
    "Ahmed",
    "Ali",
    "Omar",
    "Yusuf",
    "Ibrahim",
    "Samir",
    "Amir",
    "Karim",
    "Salim",
    "Farid",
    "Nasser",
    "Bo",
    "Dan",
]
LASTN = SCB_LASTN

_DECADE_KEYS = tuple(int(d) for d in DECADES)


def birth_decade_for_age(age: int, *, current_year: int | None = None) -> int:
    year = current_year if current_year is not None else date.today().year
    return round((year - age) / 10) * 10


def clamp_decade(decade: int) -> str:
    if decade <= _DECADE_KEYS[0]:
        return str(_DECADE_KEYS[0])
    if decade >= _DECADE_KEYS[-1]:
        return str(_DECADE_KEYS[-1])
    if decade in _DECADE_KEYS:
        return str(decade)
    return str(min(_DECADE_KEYS, key=lambda k: abs(k - decade)))


def first_name_pool_for_kon(kon: str, age: int | None) -> list[str]:
    if age is not None:
        decade = clamp_decade(birth_decade_for_age(age))
        if kon == _KON_FEMALE:
            bucket = FIRST_NAMES_BY_DECADE_F.get(decade)
            if bucket:
                return bucket
        elif kon == _KON_MALE:
            bucket = FIRST_NAMES_BY_DECADE_M.get(decade)
            if bucket:
                return bucket
    if kon == _KON_FEMALE:
        return NAMES_F
    if kon == _KON_MALE:
        return NAMES_M
    return NAMES_F


def sample_first_name(kon: str, rng: Random, age: int | None = None) -> str:
    pool = first_name_pool_for_kon(kon, age)
    if kon not in (_KON_FEMALE, _KON_MALE):
        pool = NAMES_F if rng.random() < 0.5 else NAMES_M
    return rng.choice(pool)


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
