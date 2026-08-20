"""Integration tests for list_tagger_texts topic_status wiring from variant JSON."""

from __future__ import annotations

import pytest

from app.services.anchor_pool import list_tagger_texts

INJECTION_TEXT = "Stoppa nedsläckningen av belysning i byarna."
ATTEMPT_ID = "att_topic_wiring_1"
VARIANT_ID = "main"


async def _seed_run_with_topic_variant(client) -> int:
    pops = await client.get("/populations")
    assert pops.status_code == 200
    rows = pops.json()
    if rows:
        pop_id = rows[0]["id"]
    else:
        created_pop = await client.post(
            "/populations",
            json={"name": "Topic wiring pop", "members": []},
        )
        assert created_pop.status_code == 201, created_pop.text
        pop_id = created_pop.json()["id"]

    created = await client.post(
        "/runs",
        json={
            "name": "Topic wiring run",
            "population_id": pop_id,
            "main_ticks": [
                {
                    "key": "t1",
                    "day": 1,
                    "silent": False,
                    "injections": [
                        {
                            "key": "i1",
                            "type": "party_post",
                            "sender": "@parti",
                            "text": INJECTION_TEXT,
                            "mode": "text",
                        }
                    ],
                    "rounds": 1,
                    "measurements": [],
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    from app.services import jobs as jobs_service

    factory = jobs_service.job_session_factory()
    async with factory() as session:
        from app.database.models import Run

        row = await session.get(Run, run_id)
        assert row is not None
        row.results = {
            "engine": "none",
            "attempts": [
                {
                    "id": ATTEMPT_ID,
                    "finished_at": "2026-08-20T10:00:00+00:00",
                    "seed": "42",
                    "engine": "none",
                    "variants": [
                        {
                            "id": VARIANT_ID,
                            "label": "Huvudtidslinje",
                            "ticks_run": 1,
                            "agents": [
                                {"index": 0, "member_name": "Parti", "role": "injector"},
                                {"index": 1, "member_name": "Anna", "role": "population"},
                                {"index": 2, "member_name": "Bo", "role": "population"},
                                {"index": 3, "member_name": "Cecilia", "role": "population"},
                            ],
                            "posts": [
                                {
                                    "post_id": 1,
                                    "user_id": 0,
                                    "content": INJECTION_TEXT,
                                    "num_likes": 5,
                                },
                                {
                                    "post_id": 2,
                                    "user_id": 1,
                                    "content": "Jag tycker att belysningen är viktig men vem betalar?",
                                    "num_likes": 2,
                                },
                                {
                                    "post_id": 3,
                                    "user_id": 1,
                                    "content": "Helt unrelated väderprat idag.",
                                    "num_likes": 0,
                                },
                            ],
                            "comments": [
                                {
                                    "comment_id": 1,
                                    "post_id": 1,
                                    "user_id": 2,
                                    "content": "Totally unrelated weather chat.",
                                    "num_likes": 1,
                                },
                                {
                                    "comment_id": 2,
                                    "post_id": 2,
                                    "user_id": 3,
                                    "content": "Bra förslag, konkret lösning behövs.",
                                    "num_likes": 0,
                                },
                                {
                                    "comment_id": 3,
                                    "post_id": 3,
                                    "user_id": 2,
                                    "content": "Ja det regnar verkligen.",
                                    "num_likes": 0,
                                },
                            ],
                            "measurements": [],
                            "trace": [],
                        }
                    ],
                }
            ],
        }
        row.status = "done"
        await session.commit()

    return run_id


@pytest.mark.asyncio
async def test_list_tagger_texts_wires_post_topic_status_from_variant_json(client):
    """list_tagger_texts builds RunBundle from variant JSON + run ticks and classifies posts."""
    run_id = await _seed_run_with_topic_variant(client)

    from app.services import jobs as jobs_service

    factory = jobs_service.job_session_factory()
    async with factory() as session:
        payload = await list_tagger_texts(
            session,
            run_id=run_id,
            attempt_id=ATTEMPT_ID,
            variant_id=VARIANT_ID,
            locale="sv",
            include_ssr=False,
        )

    post_topic_status = payload["post_topic_status"]
    assert post_topic_status[1] == "on_topic"
    assert post_topic_status[2] == "on_topic"
    assert post_topic_status[3] == "drifted"


@pytest.mark.asyncio
async def test_list_tagger_texts_comment_rows_inherit_topic_status(client):
    """Comment rows get topic_status via topic_status_for_comment (inherit + injection override)."""
    run_id = await _seed_run_with_topic_variant(client)

    from app.services import jobs as jobs_service

    factory = jobs_service.job_session_factory()
    async with factory() as session:
        payload = await list_tagger_texts(
            session,
            run_id=run_id,
            attempt_id=ATTEMPT_ID,
            variant_id=VARIANT_ID,
            locale="sv",
            include_ssr=False,
        )

    comment_rows = [row for row in payload["rows"] if row["source_type"] == "comment"]
    assert len(comment_rows) == 3

    by_text = {row["text"]: row["topic_status"] for row in comment_rows}
    assert by_text["Totally unrelated weather chat."] == "on_topic"
    assert by_text["Bra förslag, konkret lösning behövs."] == "on_topic"
    assert by_text["Ja det regnar verkligen."] == "drifted"


@pytest.mark.asyncio
async def test_taggable_texts_endpoint_exposes_post_topic_status(client):
    """HTTP taggable-texts response includes post_topic_status and row topic_status."""
    run_id = await _seed_run_with_topic_variant(client)

    res = await client.get(
        f"/runs/{run_id}/taggable-texts",
        params={
            "attempt_id": ATTEMPT_ID,
            "variant_id": VARIANT_ID,
            "locale": "sv",
            "include_ssr": "false",
        },
    )
    assert res.status_code == 200, res.text
    payload = res.json()

    assert payload["post_topic_status"] == {"1": "on_topic", "2": "on_topic", "3": "drifted"}

    comment_rows = [row for row in payload["rows"] if row["source_type"] == "comment"]
    by_text = {row["text"]: row["topic_status"] for row in comment_rows}
    assert by_text["Totally unrelated weather chat."] == "on_topic"
    assert by_text["Ja det regnar verkligen."] == "drifted"
