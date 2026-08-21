"""Tests for expanded persona name catalog."""

from app.services.persona_catalog import LASTN, NAMES_F, NAMES_M


def test_name_catalog_minimum_sizes():
    assert len(NAMES_F) >= 60
    assert len(NAMES_M) >= 60
    assert len(LASTN) >= 40


def test_name_catalog_entries_unique():
    assert len(NAMES_F) == len(set(NAMES_F))
    assert len(NAMES_M) == len(set(NAMES_M))
    assert len(LASTN) == len(set(LASTN))
