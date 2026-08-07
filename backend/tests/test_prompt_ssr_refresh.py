"""SSR prompt migration: obsolete forced-label tone prompts are refreshed."""

from __future__ import annotations

from app.services.prompt_catalog import (
    default_prompts,
    normalize_prompts,
    refresh_ssr_classify_prompts,
    render_prompt,
)


def test_refresh_replaces_quoted_placeholder_prompt():
    old = (
        "Klassificera varje svensk kommentar/inlägg efter ton. "
        "Tillåtna värden: {quoted}. "
        "Sarkasm = {sharp_tone}."
    )
    out = refresh_ssr_classify_prompts(
        {"report.classify.tones.system": old},
        language="sv",
    )
    text = out["report.classify.tones.system"]
    assert "{quoted}" not in text
    assert "fritext" in text.lower() or "INTE fasta" in text
    # New free-text prompt renders with no kwargs
    assert render_prompt(out, "report.classify.tones.system")


def test_normalize_prompts_refreshes_obsolete_tone():
    old = default_prompts("sv")
    old["report.classify.tones.system"] = (
        "Classify each comment/post by tone. Allowed values: {quoted}."
    )
    merged = normalize_prompts(old, language="sv", fill_missing=True)
    assert "{quoted}" not in merged["report.classify.tones.system"]
    assert render_prompt(merged, "report.classify.tones.system")
