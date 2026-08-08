"""Playground API: SSR rate/compare + prompt side-by-side (mocked embed/LLM)."""

from __future__ import annotations

import pytest

from app.llm import set_text_completer
from app.services.playground import tone_label_to_bucket
from app.services.sentiment_lexicon import classify_text
from app.services.ssr import set_embedder, tone_anchors


def test_classify_text_lexicon():
    assert classify_text("Bra förslag med hopp") == "positive"
    assert classify_text("Dåligt och uselt beslut") == "negative"
    assert classify_text("hej där") == "neutral"


def test_tone_label_to_bucket():
    labels = tone_anchors(locale="sv").labels
    assert tone_label_to_bucket("Starkt negativ", labels) == "negative"
    assert tone_label_to_bucket("Något negativ", labels) == "negative"
    assert tone_label_to_bucket("Neutral", labels) == "neutral"
    assert tone_label_to_bucket("Något positiv", labels) == "positive"
    assert tone_label_to_bucket("Starkt positiv", labels) == "positive"


def _tone_fake_embed(prefer_index: int = 0):
    """Content-aware fake: works when anchors are cache-split from texts."""
    anchors = tone_anchors(locale="sv")
    index_by_statement = {s: i for i, s in enumerate(anchors.statements)}

    async def _fake(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            idx = index_by_statement.get(text)
            if idx is None:
                v = [0.0] * 5
                v[prefer_index] = 1.0
                out.append(v)
            else:
                v = [0.0] * 5
                v[idx] = 1.0
                out.append(v)
        return out

    return _fake


@pytest.mark.asyncio
async def test_get_anchors(client):
    res = await client.get("/playground/anchors")
    assert res.status_code == 200
    data = res.json()
    assert data["version"]
    assert len(data["tone"]["sv"]["labels"]) == 5
    assert len(data["tone"]["sv"]["statements"]) == 5
    assert len(data["tone"]["nb"]["labels"]) == 5
    assert len(data["style"]["en"]["labels"]) == 6
    assert len(data["style"]["nb"]["statements"]) == 6


@pytest.mark.asyncio
async def test_ssr_rate_with_anchor_set_id(client):
    listed = await client.get("/anchor-sets?status=published&kind=tone&locale=sv")
    assert listed.status_code == 200
    anchor_id = listed.json()[0]["id"]
    set_embedder(_tone_fake_embed(0))
    res = await client.post(
        "/playground/ssr/rate",
        json={
            "texts": ["Mycket kritisk hållning."],
            "dimension": "tone",
            "locale": "sv",
            "anchor_set_id": anchor_id,
            "temperature": 0.1,
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["per_text"]
    assert data["labels"]


@pytest.mark.asyncio
async def test_ssr_rate_with_human_labels(client):
    set_embedder(_tone_fake_embed(0))
    labels = list(tone_anchors(locale="sv").labels)
    res = await client.post(
        "/playground/ssr/rate",
        json={
            "texts": ["Mycket kritisk hållning.", "Också negativ."],
            "dimension": "tone",
            "locale": "sv",
            "human_labels": [labels[0], labels[0]],
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["accuracy"] == 1.0
    assert data["per_text"][0]["predicted_label"] == labels[0]
    assert data["shares"][labels[0]] == max(data["shares"].values())
    assert labels[0] in data["confusion"]


@pytest.mark.asyncio
async def test_ssr_rate_rejects_bad_human_label(client):
    set_embedder(_tone_fake_embed(0))
    res = await client.post(
        "/playground/ssr/rate",
        json={
            "texts": ["text"],
            "human_labels": ["inte-en-etikett"],
        },
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_ssr_compare(client):
    set_embedder(_tone_fake_embed(0))
    res = await client.post(
        "/playground/ssr/compare",
        json={"texts": ["Dåligt beslut om skatten", "hej där"], "locale": "sv"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data["rows"]) == 2
    assert data["rows"][0]["ssr_bucket"] == "negative"
    assert data["rows"][0]["lexicon_label"] == "negative"
    assert data["rows"][0]["match"] is True
    assert "lexicon_shares" in data
    assert "agreement_rate" in data


@pytest.mark.asyncio
async def test_prompts_run_side_by_side(client):
    configs = (await client.get("/configurations")).json()
    assert configs
    cfg = configs[0]
    prompt_key = next(iter(cfg["prompts"]))
    source = cfg["prompts"][prompt_key]

    seen: list[str] = []

    async def _mock(messages: list[dict[str, str]]) -> str:
        system = messages[0]["content"]
        seen.append(system[:40])
        return f"svar-for-{len(seen)}"

    set_text_completer(_mock)
    res = await client.post(
        "/playground/prompts/run",
        json={
            "configuration_id": cfg["id"],
            "prompt_key": prompt_key,
            "prompt_override": source + "\n\nVARIANT B MARKER",
            "variables": {},
            "user_message": "Hej",
        },
    )
    # Many catalog prompts require placeholders — if this key needs them, pick a simple one.
    if res.status_code == 400 and "missing placeholder" in res.text:
        # Find a prompt with no {placeholders}
        prompt_key = None
        source = None
        for key, text in cfg["prompts"].items():
            if "{" not in text:
                prompt_key = key
                source = text
                break
        assert prompt_key is not None, "need a prompt without placeholders for this test"
        res = await client.post(
            "/playground/prompts/run",
            json={
                "configuration_id": cfg["id"],
                "prompt_key": prompt_key,
                "prompt_override": source + "\n\nVARIANT B MARKER",
                "variables": {},
                "user_message": "Hej",
            },
        )
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data["variants"]) == 2
    assert data["variants"][0]["id"] == "A"
    assert data["variants"][1]["id"] == "B"
    assert "VARIANT B MARKER" in data["variants"][1]["rendered_prompt"]
    assert data["variants"][0]["response"] == "svar-for-1"
    assert data["variants"][1]["response"] == "svar-for-2"


@pytest.mark.asyncio
async def test_prompts_run_missing_config(client):
    res = await client.post(
        "/playground/prompts/run",
        json={"configuration_id": 999999, "prompt_key": "persona.system"},
    )
    assert res.status_code == 404
