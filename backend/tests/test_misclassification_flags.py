"""Tests for SSR misclassification flags."""

from __future__ import annotations

import pytest

from app.services.anchor_pool import drop_centroid_cache
from app.services.ssr import set_embedder


@pytest.fixture
def mock_embedder():
    async def _mock(texts: list[str]) -> list[list[float]]:
        return [[float((hash(t) + i) % 7) for i in range(8)] for t in texts]

    set_embedder(_mock)
    drop_centroid_cache()
    yield
    set_embedder(None)
    drop_centroid_cache()


async def _seed_run_with_comment(client) -> tuple[int, str, str]:
    pops = await client.get("/populations")
    assert pops.status_code == 200
    rows = pops.json()
    if rows:
        pop_id = rows[0]["id"]
    else:
        created_pop = await client.post(
            "/populations",
            json={"name": "Misclass pop", "members": []},
        )
        assert created_pop.status_code == 201, created_pop.text
        pop_id = created_pop.json()["id"]

    created = await client.post(
        "/runs",
        json={
            "name": "Misclass flag run",
            "population_id": pop_id,
            "main_ticks": [],
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    attempt_id = "att_misclass_1"

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
                    "id": attempt_id,
                    "finished_at": "2026-08-16T10:00:00+00:00",
                    "seed": "42",
                    "engine": "none",
                    "variants": [
                        {
                            "id": "main",
                            "label": "Huvudtidslinje",
                            "ticks_run": 1,
                            "agents": [],
                            "posts": [],
                            "comments": [
                                {
                                    "comment_id": 1,
                                    "post_id": 1,
                                    "user_id": 1,
                                    "content": "Det här budskapet känns fel.",
                                    "num_likes": 0,
                                }
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

    return run_id, attempt_id, "main"


async def test_create_list_dismiss_misclassification_flag(client, mock_embedder):
    run_id, attempt_id, variant_id = await _seed_run_with_comment(client)

    create = await client.post(
        f"/runs/{run_id}/misclassification-flags",
        json={
            "text": "Det här är ju helt fel ton.",
            "predicted_label": "Starkt positiv",
            "expected_label": "Starkt negativ",
            "kind": "tone",
            "source_type": "comment",
            "source_ref": {"type": "comment", "comment_id": 42},
            "attempt_id": attempt_id,
            "variant_id": variant_id,
            "locale": "sv",
        },
    )
    assert create.status_code == 201, create.text
    flag = create.json()
    assert flag["status"] == "open"
    assert flag["predicted_label"] == "Starkt positiv"
    assert flag["expected_label"] == "Starkt negativ"
    assert flag["kind"] == "tone"
    anchor_set_id = flag["anchor_set_id"]
    flag_id = flag["id"]

    listed = await client.get(
        f"/anchor-sets/{anchor_set_id}/misclassification-flags?status=open"
    )
    assert listed.status_code == 200
    assert any(row["id"] == flag_id for row in listed.json())

    dismissed = await client.patch(
        f"/anchor-sets/{anchor_set_id}/misclassification-flags/{flag_id}",
        json={"status": "dismissed"},
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"
    assert dismissed.json()["resolved_at"]

    open_again = await client.get(
        f"/anchor-sets/{anchor_set_id}/misclassification-flags?status=open"
    )
    assert not any(row["id"] == flag_id for row in open_again.json())


async def test_resolve_misclassification_flag_adds_pool_item(client, mock_embedder):
    run_id, attempt_id, variant_id = await _seed_run_with_comment(client)
    text = "Unik misclass resolve text för pool."

    create = await client.post(
        f"/runs/{run_id}/misclassification-flags",
        json={
            "text": text,
            "predicted_label": "Neutral",
            "expected_label": "Något negativ",
            "kind": "tone",
            "source_type": "comment",
            "source_ref": {"type": "comment", "comment_id": 7},
            "attempt_id": attempt_id,
            "variant_id": variant_id,
            "locale": "sv",
        },
    )
    assert create.status_code == 201, create.text
    flag = create.json()
    anchor_set_id = flag["anchor_set_id"]
    flag_id = flag["id"]

    resolved = await client.patch(
        f"/anchor-sets/{anchor_set_id}/misclassification-flags/{flag_id}",
        json={"status": "resolved", "add_to_calibration": False},
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "resolved"
    assert body["pool_item_id"] is not None

    pool = await client.get(f"/anchor-sets/{anchor_set_id}/pool")
    assert pool.status_code == 200
    assert any(
        row["id"] == body["pool_item_id"] and row["label"] == "Något negativ"
        for row in pool.json()
    )


async def test_same_predicted_and_expected_rejected(client, mock_embedder):
    run_id, attempt_id, variant_id = await _seed_run_with_comment(client)
    res = await client.post(
        f"/runs/{run_id}/misclassification-flags",
        json={
            "text": "Samma etikett ska avvisas.",
            "predicted_label": "Neutral",
            "expected_label": "Neutral",
            "kind": "tone",
            "source_type": "comment",
            "source_ref": {"type": "comment", "comment_id": 1},
            "attempt_id": attempt_id,
            "variant_id": variant_id,
            "locale": "sv",
        },
    )
    assert res.status_code == 400


async def test_taggable_texts_include_ssr_predictions(client, mock_embedder):
    """With include_ssr=true, rows expose tone/style predicted labels when texts exist."""
    run_id, attempt_id, variant_id = await _seed_run_with_comment(client)
    res = await client.get(
        f"/runs/{run_id}/taggable-texts",
        params={
            "attempt_id": attempt_id,
            "variant_id": variant_id,
            "locale": "sv",
            "include_ssr": "true",
        },
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["include_ssr"] is True
    assert len(payload["rows"]) >= 1
    for row in payload["rows"]:
        assert row["tone_predicted"] is not None
        assert row["style_predicted"] is not None
        assert row["tone_pmf"] is not None
        assert row["style_pmf"] is not None

    off = await client.get(
        f"/runs/{run_id}/taggable-texts",
        params={
            "attempt_id": attempt_id,
            "variant_id": variant_id,
            "locale": "sv",
            "include_ssr": "false",
        },
    )
    assert off.status_code == 200
    assert off.json()["include_ssr"] is False
    for row in off.json()["rows"]:
        assert row["tone_predicted"] is None
        assert row["style_predicted"] is None


async def test_taggable_texts_empty_attempt_returns_no_rows(client, mock_embedder):
    """Attempts without posts/comments/agents are taggable as an empty list, not 500."""
    pops = await client.get("/populations")
    assert pops.status_code == 200
    rows = pops.json()
    if rows:
        pop_id = rows[0]["id"]
    else:
        created_pop = await client.post(
            "/populations",
            json={"name": "Empty attempt pop", "members": []},
        )
        assert created_pop.status_code == 201, created_pop.text
        pop_id = created_pop.json()["id"]

    created = await client.post(
        "/runs",
        json={"name": "Empty attempt run", "population_id": pop_id, "main_ticks": []},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    attempt_id = "att_empty_1"

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
                    "id": attempt_id,
                    "finished_at": "2026-08-16T10:00:00+00:00",
                    "variants": [
                        {
                            "id": "a",
                            "label": "Huvudspår",
                            "ticks_run": 0,
                            "agents": [],
                            "posts": [],
                            "comments": [],
                        }
                    ],
                }
            ],
        }
        row.status = "done"
        await session.commit()

    res = await client.get(
        f"/runs/{run_id}/taggable-texts",
        params={
            "attempt_id": attempt_id,
            "variant_id": "a",
            "locale": "sv",
            "include_ssr": "false",
        },
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["rows"] == []
    assert payload["attempt_id"] == attempt_id
