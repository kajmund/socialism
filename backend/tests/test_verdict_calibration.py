"""Verdict calibration API and recommendation snapshot in report.ssr.json."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.services import jobs as jobs_service
from app.services.report import ARTIFACT_ROOT
from tests.test_report_api import _seed_run_with_attempt


async def _generate_report(client, tmp_path, monkeypatch) -> str:
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
                "title": "Kalibreringstest",
            },
        )
        assert resp.status_code == 202, resp.text
        report_id = resp.json()["id"]
        await asyncio.wait_for(done.wait(), timeout=30)
        return report_id
    finally:
        set_structured_completer(None)
        set_embedder(None)
        jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_report_ssr_json_includes_recommendation(client, tmp_path, monkeypatch):
    report_id = await _generate_report(client, tmp_path, monkeypatch)
    ssr_path = Path(ARTIFACT_ROOT) / report_id / "report.ssr.json"
    doc = json.loads(ssr_path.read_text(encoding="utf-8"))
    rec = doc["recommendation"]
    assert isinstance(rec["score"], int)
    assert rec["action"]
    assert rec["verdict_key"] in {"zero", "strong", "mixed", "weak"}


@pytest.mark.asyncio
async def test_verdict_calibration_get_before_save(client, tmp_path, monkeypatch):
    report_id = await _generate_report(client, tmp_path, monkeypatch)
    res = await client.get(f"/reports/{report_id}/verdict-calibration")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["report_id"] == report_id
    assert data["matches"] is None
    assert data["note"] is None
    assert data["recommendation"]["action"]
    assert data["updated_at"] is None


@pytest.mark.asyncio
async def test_verdict_calibration_upsert(client, tmp_path, monkeypatch):
    report_id = await _generate_report(client, tmp_path, monkeypatch)
    first = await client.post(
        f"/reports/{report_id}/verdict-calibration",
        json={"matches": True, "note": "Stämmer bra"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["matches"] is True
    assert first.json()["note"] == "Stämmer bra"
    assert first.json()["updated_at"]

    second = await client.post(
        f"/reports/{report_id}/verdict-calibration",
        json={"matches": False, "note": "För optimistisk"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["matches"] is False
    assert second.json()["note"] == "För optimistisk"

    got = await client.get(f"/reports/{report_id}/verdict-calibration")
    assert got.json()["matches"] is False


@pytest.mark.asyncio
async def test_verdict_calibration_requires_succeeded(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_id, attempt_id = await _seed_run_with_attempt(client)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    try:
        resp = await client.post(
            "/reports",
            json={"sources": [{"run_id": run_id, "attempt_id": attempt_id}]},
        )
        assert resp.status_code == 202
        report_id = resp.json()["id"]
        res = await client.get(f"/reports/{report_id}/verdict-calibration")
        assert res.status_code == 404
    finally:
        jobs_service.set_schedule_hook(None)
