"""Tests for OKF corpus loader."""

from __future__ import annotations

from pathlib import Path

from integrations.okf.corpus import load_guides, search_guides


def test_load_guides_from_repo_manual():
    root = Path(__file__).resolve().parents[2] / "knowledge" / "manual"
    guides = load_guides(root)
    assert len(guides) >= 10
    titles = {g.title for g in guides}
    assert "Översikt av ytorna" in titles


def test_search_guides_ranks_by_overlap():
    root = Path(__file__).resolve().parents[2] / "knowledge" / "manual"
    guides = load_guides(root)
    hits = search_guides(guides, "population recept generera", limit=2)
    assert hits
    assert any("population" in g.slug for g in hits)
