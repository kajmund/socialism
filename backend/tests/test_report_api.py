"""API tests for report ordering."""

from __future__ import annotations

import asyncio

import pytest

from app.services import jobs as jobs_service


async def _seed_run_with_attempt(client) -> tuple[int, str]:
    persona = (
        await client.post(
            "/personas",
            json={
                "id": "rp1",
                "name": "Rapport Persona",
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
                "name": "Rapportpop",
                "fingerprint": [[33, 34, 33], [33, 34, 33], [33, 34, 33]],
                "recipe": {},
                "members": [
                    {
                        "persona_id": persona["id"],
                        "name": persona["name"],
                        "initials": "RP",
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
                "name": "Rapportrun",
                "population_id": pop["id"],
                "seed": "1",
                "main_ticks": [],
            },
        )
    ).json()
    run_id = run["id"]

    # Inject fake attempt results via direct DB through start+none engine leaves empty —
    # patch results via put isn't available; use jobs session to update run.
    from app.database.models import Run

    factory = jobs_service.job_session_factory()
    attempt_id = "att_test_1"
    async with factory() as session:
        row = await session.get(Run, run_id)
        assert row is not None
        row.results = {
            "engine": "none",
            "attempts": [
                {
                    "id": attempt_id,
                    "finished_at": "2026-08-03T12:00:00+00:00",
                    "seed": "1",
                    "engine": "none",
                    "variants": [
                        {
                            "id": "main",
                            "label": "Huvudtidslinje",
                            "ticks_run": 2,
                            "agents": [
                                {"index": 0, "member_name": "Anna", "role": "user"},
                                {"index": 1, "member_name": "Bo", "role": "user"},
                            ],
                            "posts": [
                                {
                                    "post_id": 1,
                                    "user_id": 0,
                                    "content": "Äldreomsorg och hemtjänst.",
                                    "num_likes": 3,
                                }
                            ],
                            "comments": [
                                {
                                    "comment_id": 1,
                                    "post_id": 1,
                                    "user_id": 1,
                                    "content": "Bra förslag om trafik och a-traktor.",
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


@pytest.mark.asyncio
async def test_create_report_and_generate(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_id, attempt_id = await _seed_run_with_attempt(client)

    done = asyncio.Event()

    def hook(job_id: str) -> None:
        async def _go() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_go())

    jobs_service.set_schedule_hook(hook)

    resp = await client.post(
        "/reports",
        json={"sources": [{"run_id": run_id, "attempt_id": attempt_id}], "title": "Min rapport"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["job_id"]
    report_id = body["id"]

    await asyncio.wait_for(done.wait(), timeout=30)

    got = await client.get(f"/reports/{report_id}")
    assert got.status_code == 200
    data = got.json()
    assert data["status"] == "succeeded"
    assert data["html_path"]

    html = await client.get(f"/reports/{report_id}/html")
    assert html.status_code == 200
    assert "text/html" in html.headers.get("content-type", "")
    assert b"donut" in html.content or b"info-kpi" in html.content or b"pyramid" in html.content


@pytest.mark.asyncio
async def test_create_report_missing_attempt(client):
    persona = (
        await client.post(
            "/personas",
            json={
                "id": "rp2",
                "name": "X",
                "age": 30,
                "occ": "Y",
                "district": "Z",
                "quote": "q",
                "origin": "manuell",
            },
        )
    ).json()
    pop = (
        await client.post(
            "/populations",
            json={
                "name": "EmptyPop",
                "fingerprint": [[33, 34, 33], [33, 34, 33], [33, 34, 33]],
                "recipe": {},
                "members": [
                    {
                        "persona_id": persona["id"],
                        "name": "X",
                        "initials": "X",
                        "age": 30,
                        "occ": "Y",
                        "district": "Z",
                        "trait": "q",
                    }
                ],
            },
        )
    ).json()
    run = (
        await client.post(
            "/runs",
            json={"name": "Empty", "population_id": pop["id"], "seed": "1", "main_ticks": []},
        )
    ).json()
    resp = await client.post(
        "/reports",
        json={"sources": [{"run_id": run["id"], "attempt_id": "missing"}]},
    )
    assert resp.status_code == 400
