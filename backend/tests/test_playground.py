"""Playground API: SSR rate/compare + prompt side-by-side (mocked embed/LLM)."""

from __future__ import annotations

import pytest

from app.llm import set_text_completer
from app.services.playground import tone_label_to_bucket
from app.services.report.sampling import SAMPLING_METHOD
from app.services.sentiment_lexicon import classify_text
from app.services.ssr import set_embedder, tone_anchors


async def _seed_run_with_reactions(client) -> tuple[int, str]:
    """Minimal done run with posts/comments for playground sampling."""
    persona = (
        await client.post(
            "/personas",
            json={
                "id": "pg1",
                "name": "Playground Persona",
                "age": 40,
                "occ": "Lärare",
                "district": "Centrum",
                "quote": "Quote",
                "origin": "manuell",
            },
        )
    ).json()
    pop = (
        await client.post(
            "/populations",
            json={
                "name": "Playgroundpop",
                "fingerprint": [[33, 34, 33], [33, 34, 33], [33, 34, 33]],
                "recipe": {},
                "members": [
                    {
                        "persona_id": persona["id"],
                        "name": persona["name"],
                        "initials": "PG",
                        "age": 40,
                        "occ": "Lärare",
                        "district": "Centrum",
                        "trait": "Quote",
                    }
                ],
            },
        )
    ).json()
    run = (
        await client.post(
            "/runs",
            json={
                "name": "Playgroundrun",
                "population_id": pop["id"],
                "main_ticks": [
                    {
                        "key": "t1",
                        "day": 1,
                        "injections": [
                            {
                                "key": "inj1",
                                "type": "party_post",
                                "text": "Äldreomsorg och hemtjänst behöver mer resurser.",
                            }
                        ],
                    }
                ],
            },
        )
    ).json()
    run_id = run["id"]

    from app.services import jobs as jobs_service

    factory = jobs_service.job_session_factory()
    attempt_id = "att_pg_1"
    async with factory() as session:
        from app.database.models import Run

        row = await session.get(Run, run_id)
        assert row is not None
        row.results = {
            "engine": "none",
            "attempts": [
                {
                    "id": attempt_id,
                    "finished_at": "2026-08-03T12:00:00+00:00",
                    "seed": "42",
                    "engine": "none",
                    "variants": [
                        {
                            "id": "main",
                            "label": "Huvudtidslinje",
                            "ticks_run": 2,
                            "agents": [
                                {"index": 0, "member_name": "Parti", "role": "injector"},
                                {"index": 1, "member_name": "Anna", "role": "user"},
                                {"index": 2, "member_name": "Bo", "role": "user"},
                            ],
                            "posts": [
                                {
                                    "post_id": 1,
                                    "user_id": 0,
                                    "content": "Äldreomsorg och hemtjänst behöver mer resurser.",
                                    "num_likes": 5,
                                },
                                {
                                    "post_id": 2,
                                    "user_id": 1,
                                    "content": "Äldreomsorgen måste bli bättre i kommunen.",
                                    "num_likes": 3,
                                },
                            ],
                            "comments": [
                                {
                                    "comment_id": 1,
                                    "post_id": 1,
                                    "user_id": 2,
                                    "content": "Bra förslag om äldreomsorg.",
                                    "num_likes": 1,
                                }
                            ],
                            "measurements": [],
                        }
                    ],
                }
            ],
        }
        row.status = "done"
        await session.commit()
    return run_id, attempt_id


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
    assert len(data["style"]["en"]["labels"]) == 6


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
async def test_ssr_sample_from_run(client):
    run_id, attempt_id = await _seed_run_with_reactions(client)
    res = await client.post(
        "/playground/ssr/sample-from-run",
        json={
            "run_id": run_id,
            "attempt_id": attempt_id,
            "use_report_sampling": True,
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data["texts"]) == 2
    assert data["sampling"]["method"] == SAMPLING_METHOD
    assert data["sampling"]["eligible_count"] == 2
    assert len(data["clipped_preview"]) == 2


@pytest.mark.asyncio
async def test_ssr_sample_from_run_all_reactions(client):
    run_id, attempt_id = await _seed_run_with_reactions(client)
    res = await client.post(
        "/playground/ssr/sample-from-run",
        json={
            "run_id": run_id,
            "attempt_id": attempt_id,
            "use_report_sampling": False,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["sampling"]["method"] == "all"


@pytest.mark.asyncio
async def test_ssr_sample_from_run_no_reactions(client):
    run_id, attempt_id = await _seed_run_with_reactions(client)
    from app.services import jobs as jobs_service

    factory = jobs_service.job_session_factory()
    async with factory() as session:
        from app.database.models import Run

        row = await session.get(Run, run_id)
        assert row is not None
        results = dict(row.results or {})
        attempts = [dict(a) for a in results.get("attempts") or []]
        variants = [dict(v) for v in attempts[0].get("variants") or []]
        variants[0] = {**variants[0], "posts": [], "comments": []}
        attempts[0] = {**attempts[0], "variants": variants}
        results["attempts"] = attempts
        row.results = results
        await session.commit()
    res = await client.post(
        "/playground/ssr/sample-from-run",
        json={"run_id": run_id, "attempt_id": attempt_id},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_ssr_rate_clip_for_embed(client):
    embedded: list[str] = []

    async def _capture_embed(texts: list[str]) -> list[list[float]]:
        embedded.extend(texts)
        return [[1.0, 0.0, 0.0, 0.0, 0.0] for _ in texts]

    long_text = "x" * 250
    set_embedder(_capture_embed)
    try:
        res = await client.post(
            "/playground/ssr/rate",
            json={
                "texts": [long_text],
                "clip_for_embed": True,
            },
        )
        assert res.status_code == 200, res.text
        clipped = [text for text in embedded if text.startswith("x")]
        assert len(clipped) == 1
        assert len(clipped[0]) == 200
        assert res.json()["per_text"][0]["text"] == long_text
    finally:
        set_embedder(None)


@pytest.mark.asyncio
async def test_ssr_rate_use_config_temperature(client, monkeypatch):
    configs = (await client.get("/configurations")).json()
    cfg_id = configs[0]["id"]
    await client.patch(f"/configurations/{cfg_id}", json={"ssr_temperature": 0.001})

    captured: list[float] = []

    async def _fake_rate_case(*_args, **kwargs):
        captured.append(float(kwargs["temperature"]))
        return {
            "anchor_set_name": "tone",
            "anchor_set_version": "v1",
            "labels": list(tone_anchors(locale="sv").labels),
            "shares": {},
            "per_text": [],
        }

    monkeypatch.setattr("app.api.playground.rate_case", _fake_rate_case)
    res = await client.post(
        "/playground/ssr/rate",
        json={
            "texts": ["test"],
            "use_config_temperature": True,
            "temperature": 1.0,
        },
    )
    assert res.status_code == 200, res.text
    assert captured == [0.001]


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
