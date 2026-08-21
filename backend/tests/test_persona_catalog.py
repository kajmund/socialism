"""Age-weighted SCB name catalog helpers."""

from random import Random

from app.services.persona_catalog import (
    LASTN,
    NAMES_F,
    NAMES_M,
    birth_decade_for_age,
    clamp_decade,
    first_name_pool_for_kon,
    sample_first_name,
)
from app.services.persona_catalog_scb_names import (
    DECADES,
    FIRST_NAMES_BY_DECADE_F,
    FIRST_NAMES_BY_DECADE_M,
    SCB_LASTN,
)


def test_scb_static_data_has_decades_and_surnames():
    assert len(DECADES) >= 8
    assert len(FIRST_NAMES_BY_DECADE_F) >= 8
    assert len(FIRST_NAMES_BY_DECADE_M) >= 8
    assert len(SCB_LASTN) >= 50
    assert LASTN == SCB_LASTN


def test_birth_decade_for_age():
    assert birth_decade_for_age(72, current_year=2026) == 1950
    assert birth_decade_for_age(24, current_year=2026) == 2000


def test_clamp_decade_edges():
    assert clamp_decade(1910) == DECADES[0]
    assert clamp_decade(2035) == DECADES[-1]


def test_recent_female_decades_differ():
    assert set(FIRST_NAMES_BY_DECADE_F["1980"]) != set(FIRST_NAMES_BY_DECADE_F["2010"])
    assert set(FIRST_NAMES_BY_DECADE_M["1980"]) != set(FIRST_NAMES_BY_DECADE_M["2010"])
    modern = set(FIRST_NAMES_BY_DECADE_F["2010"]) | set(FIRST_NAMES_BY_DECADE_F["2000"])
    assert {"Alice", "Elsa"} & modern


def test_decade_buckets_are_not_all_identical():
    female_signatures = {tuple(names) for names in FIRST_NAMES_BY_DECADE_F.values()}
    male_signatures = {tuple(names) for names in FIRST_NAMES_BY_DECADE_M.values()}
    assert len(female_signatures) > len(FIRST_NAMES_BY_DECADE_F) // 2
    assert len(male_signatures) > len(FIRST_NAMES_BY_DECADE_M) // 2


def test_first_name_pool_uses_decade_bucket():
    pool_old = first_name_pool_for_kon("Kvinna", 75)
    pool_young = first_name_pool_for_kon("Kvinna", 24)
    assert pool_old != NAMES_F
    assert pool_young != NAMES_F
    assert "Wilma" not in pool_old
    assert "Doris" not in pool_young


def test_first_name_pool_falls_back_without_age():
    assert first_name_pool_for_kon("Kvinna", None) == NAMES_F
    assert first_name_pool_for_kon("Man", None) == NAMES_M


def test_old_male_names_differ_from_young():
    old = set(first_name_pool_for_kon("Man", 70))
    young = set(first_name_pool_for_kon("Man", 25))
    assert "Gösta" in old or "Rune" in old
    assert "William" in young or "Lucas" in young


def test_sample_first_name_respects_pool(monkeypatch):
    monkeypatch.setitem(
        FIRST_NAMES_BY_DECADE_M,
        "1950",
        ["Stig"],
    )
    rng = Random(0)
    assert sample_first_name("Man", rng, age=75) == "Stig"
