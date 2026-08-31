"""API tests for report ordering."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.database.models import Report
from app.serializers import utcnow
from app.services import jobs as jobs_service
from app.services.report import ARTIFACT_ROOT


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
    from app.llm import set_structured_completer
    from app.services.ssr import set_embedder

    async def mock_embed(texts: list[str]) -> list[list[float]]:
        return [[float((hash(t) + i) % 7) for i in range(8)] for t in texts]

    async def mock_llm(_messages, _response_model):
        raise AssertionError("quick report must not call DeepSeek")

    set_structured_completer(mock_llm)
    set_embedder(mock_embed)
    monkeypatch.chdir(tmp_path)
    run_id, attempt_id = await _seed_run_with_attempt(client)

    done = asyncio.Event()

    def hook(job_id: str) -> None:
        async def _go() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_go())

    jobs_service.set_schedule_hook(hook)

    try:
        resp = await client.post(
            "/reports",
            json={
                "sources": [{"run_id": run_id, "attempt_id": attempt_id}],
                "title": "Min rapport",
                "locale": "sv",
            },
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        assert body["locale"] == "sv"
        assert body["mode"] == "quick"
        assert body["job_id"]
        report_id = body["id"]

        await asyncio.wait_for(done.wait(), timeout=30)

        got = await client.get(f"/reports/{report_id}")
        assert got.status_code == 200
        data = got.json()
        assert data["status"] == "succeeded"
        assert data["html_path"]
        assert data["locale"] == "sv"
        assert data["mode"] == "quick"

        html = await client.get(f"/reports/{report_id}/html")
        assert html.status_code == 200
        assert "text/html" in html.headers.get("content-type", "")
        assert "rapport.html" in html.headers.get("content-disposition", "")
        assert (
            b"donut" in html.content
            or b"stats-table" in html.content
            or b"chart-grid" in html.content
        )
    finally:
        set_structured_completer(None)
        set_embedder(None)


@pytest.mark.asyncio
async def test_create_english_report_locale(client, tmp_path, monkeypatch):
    from app.llm import set_structured_completer
    from app.services.ssr import set_embedder

    async def mock_embed(texts: list[str]) -> list[list[float]]:
        return [[float((hash(t) + i) % 7) for i in range(8)] for t in texts]

    async def mock_llm(_messages, _response_model):
        raise AssertionError("quick report must not call DeepSeek")

    set_structured_completer(mock_llm)
    set_embedder(mock_embed)
    monkeypatch.chdir(tmp_path)
    run_id, attempt_id = await _seed_run_with_attempt(client)

    configs = (await client.get("/configurations")).json()
    en_cfg = next(c for c in configs if c["language"] == "en")
    activated = await client.post(f"/configurations/{en_cfg['id']}/activate")
    assert activated.status_code == 200

    done = asyncio.Event()

    def hook(job_id: str) -> None:
        async def _go() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_go())

    jobs_service.set_schedule_hook(hook)

    try:
        resp = await client.post(
            "/reports",
            json={
                "sources": [{"run_id": run_id, "attempt_id": attempt_id}],
                "title": "My report",
                "locale": "en",
            },
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["locale"] == "en"
        assert body["mode"] == "quick"
        report_id = body["id"]

        await asyncio.wait_for(done.wait(), timeout=30)

        got = (await client.get(f"/reports/{report_id}")).json()
        assert got["status"] == "succeeded"
        assert got["locale"] == "en"

        html = await client.get(f"/reports/{report_id}/html")
        assert html.status_code == 200
        assert "report.html" in html.headers.get("content-disposition", "")
        assert b'lang="en"' in html.content
        assert b"Quick report" in html.content
    finally:
        set_structured_completer(None)
        set_embedder(None)


@pytest.mark.asyncio
async def test_report_setup_failure_marks_report_failed(client, tmp_path, monkeypatch):
    """Pre-generation setup errors must fail the report, not leave it running."""
    run_id, attempt_id = await _seed_run_with_attempt(client)
    monkeypatch.chdir(tmp_path)

    async def boom(_session, _sources):
        raise ValueError("simulated bundle build failure")

    monkeypatch.setattr(
        "app.services.report.bundles.build_bundles",
        boom,
    )

    done = asyncio.Event()

    def hook(job_id: str) -> None:
        async def _go() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_go())

    jobs_service.set_schedule_hook(hook)

    try:
        resp = await client.post(
            "/reports",
            json={
                "sources": [{"run_id": run_id, "attempt_id": attempt_id}],
                "title": "Fail test",
            },
        )
        assert resp.status_code == 202
        report_id = resp.json()["id"]
        job_id = resp.json()["job_id"]

        await asyncio.wait_for(done.wait(), timeout=30)

        got = await client.get(f"/reports/{report_id}")
        assert got.status_code == 200
        data = got.json()
        assert data["status"] == "failed", data
        assert "simulated bundle build failure" in (data.get("error") or "")

        job = await client.get(f"/jobs/{job_id}")
        assert job.status_code == 200
        assert job.json()["status"] == "failed"
    finally:
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_english_report_fails_while_sv_active(client, tmp_path, monkeypatch):
    """English reports require an active en configuration for anchors — no silent fallback."""
    from app.llm import set_structured_completer
    from app.services.ssr import set_embedder

    async def mock_embed(texts: list[str]) -> list[list[float]]:
        return [[float((hash(t) + i) % 7) for i in range(8)] for t in texts]

    async def mock_llm(_messages, _response_model):
        raise AssertionError("LLM must not run when active language mismatches report locale")

    configs = (await client.get("/configurations")).json()
    active = [c for c in configs if c["is_active"]]
    assert len(active) == 1
    assert active[0]["language"] == "sv"

    set_structured_completer(mock_llm)
    set_embedder(mock_embed)
    monkeypatch.chdir(tmp_path)
    run_id, attempt_id = await _seed_run_with_attempt(client)

    done = asyncio.Event()

    def hook(job_id: str) -> None:
        async def _go() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_go())

    jobs_service.set_schedule_hook(hook)

    try:
        resp = await client.post(
            "/reports",
            json={
                "sources": [{"run_id": run_id, "attempt_id": attempt_id}],
                "title": "English anchors test",
                "locale": "en",
            },
        )
        assert resp.status_code == 202, resp.text
        report_id = resp.json()["id"]
        await asyncio.wait_for(done.wait(), timeout=30)

        got = await client.get(f"/reports/{report_id}")
        assert got.status_code == 200
        data = got.json()
        assert data["status"] == "failed"
        assert "language" in (data.get("error") or "").lower() or "en" in (data.get("error") or "")
    finally:
        set_structured_completer(None)
        set_embedder(None)


@pytest.mark.asyncio
async def test_english_report_succeeds_when_en_active(client, tmp_path, monkeypatch):
    """With en active, English report locale resolves anchors and generates snabbrapport."""
    from app.llm import set_structured_completer
    from app.services.ssr import set_embedder

    async def mock_embed(texts: list[str]) -> list[list[float]]:
        return [[float((hash(t) + i) % 7) for i in range(8)] for t in texts]

    async def mock_llm(_messages, _response_model):
        raise AssertionError("quick report must not call DeepSeek")

    configs = (await client.get("/configurations")).json()
    en_cfg = next(c for c in configs if c["language"] == "en")
    activated = await client.post(f"/configurations/{en_cfg['id']}/activate")
    assert activated.status_code == 200

    set_structured_completer(mock_llm)
    set_embedder(mock_embed)
    monkeypatch.chdir(tmp_path)
    run_id, attempt_id = await _seed_run_with_attempt(client)

    done = asyncio.Event()

    def hook(job_id: str) -> None:
        async def _go() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_go())

    jobs_service.set_schedule_hook(hook)

    try:
        resp = await client.post(
            "/reports",
            json={
                "sources": [{"run_id": run_id, "attempt_id": attempt_id}],
                "title": "English anchors test",
                "locale": "en",
            },
        )
        assert resp.status_code == 202, resp.text
        report_id = resp.json()["id"]
        await asyncio.wait_for(done.wait(), timeout=30)

        got = await client.get(f"/reports/{report_id}")
        assert got.status_code == 200
        assert got.json()["status"] == "succeeded"
        assert got.json()["mode"] == "quick"
    finally:
        set_structured_completer(None)
        set_embedder(None)


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
            json={"name": "Empty", "population_id": pop["id"], "main_ticks": []},
        )
    ).json()
    resp = await client.post(
        "/reports",
        json={"sources": [{"run_id": run["id"], "attempt_id": "missing"}]},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_report_removes_row_and_artifacts(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report_id = "rpt_delete_me"
    artifact_dir = Path(ARTIFACT_ROOT) / report_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "report.html").write_text("<html>bye</html>", encoding="utf-8")

    factory = jobs_service.job_session_factory()
    async with factory() as session:
        session.add(
            Report(
                id=report_id,
                customer_id=1,
                status="succeeded",
                title="Att ta bort",
                locale="sv",
                mode="quick",
                sources=[],
                html_path=str(artifact_dir / "report.html"),
                slots_path=None,
                job_id=None,
                error=None,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        await session.commit()

    listed = await client.get("/reports")
    assert listed.status_code == 200
    assert any(r["id"] == report_id for r in listed.json())

    deleted = await client.delete(f"/reports/{report_id}")
    assert deleted.status_code == 204
    assert not artifact_dir.exists()

    missing = await client.get(f"/reports/{report_id}")
    assert missing.status_code == 404

    again = await client.delete(f"/reports/{report_id}")
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_bulk_delete_reports(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = ["rpt_bulk_a", "rpt_bulk_b", "rpt_bulk_missing"]
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        for report_id in ids[:2]:
            artifact_dir = Path(ARTIFACT_ROOT) / report_id
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "report.html").write_text("<html/>", encoding="utf-8")
            session.add(
                Report(
                    id=report_id,
                    customer_id=1,
                    status="succeeded",
                    title=report_id,
                    locale="sv",
                    mode="quick",
                    sources=[],
                    html_path=str(artifact_dir / "report.html"),
                    slots_path=None,
                    job_id=None,
                    error=None,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
        await session.commit()

    resp = await client.post("/reports/bulk-delete", json={"ids": ids})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["deleted_ids"]) == {"rpt_bulk_a", "rpt_bulk_b"}
    assert not (Path(ARTIFACT_ROOT) / "rpt_bulk_a").exists()
    assert not (Path(ARTIFACT_ROOT) / "rpt_bulk_b").exists()

    empty = await client.post(
        "/reports/bulk-delete",
        json={"ids": ["rpt_bulk_missing", "rpt_never"]},
    )
    assert empty.status_code == 404
