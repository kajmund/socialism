"""Tests for run log tail reading."""

from __future__ import annotations

import pytest

from app.services.run_log import (
    read_run_log_tail,
    run_variant_log_path,
    tail_run_log_file,
    validate_log_segment,
    write_run_log_note,
)


def test_validate_log_segment_rejects_traversal():
    with pytest.raises(ValueError, match="Invalid attempt_id"):
        validate_log_segment("attempt_id", "../etc")


def test_tail_run_log_file_returns_last_lines(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = run_variant_log_path(3, "att_abc", "main")
    write_run_log_note(path, "\n".join(f"line-{i}" for i in range(1, 6)))
    content, truncated = tail_run_log_file(path, lines=2)
    assert truncated is False
    assert content.splitlines() == ["line-4", "line-5"]


def test_tail_run_log_file_byte_truncated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = run_variant_log_path(4, "att_big", "main")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * 300_000 + "\nfinal-line\n", encoding="utf-8")
    content, truncated = tail_run_log_file(path, lines=5, max_bytes=4096)
    assert truncated is True
    assert content.endswith("final-line")


def test_read_run_log_tail_resolves_under_artifact_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = run_variant_log_path(9, "att_ok", "variant-a")
    write_run_log_note(path, "engine=oasis\nstatus=failed\nreason=demo")
    resolved, content, truncated = read_run_log_tail(
        run_id=9,
        attempt_id="att_ok",
        variant_id="variant-a",
        lines=10,
    )
    assert resolved == path.resolve()
    assert "reason=demo" in content
    assert truncated is False


def test_read_run_log_tail_missing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        read_run_log_tail(
            run_id=1,
            attempt_id="att_missing",
            variant_id="main",
            lines=10,
        )


async def test_get_run_log_tail_api(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from app.services import jobs as jobs_service

    jobs_service.set_schedule_hook(lambda _job_id: None)

    pop = (
        await client.post(
            "/populations",
            json={"name": "Logpop", "members": []},
        )
    ).json()
    run = (
        await client.post(
            "/runs",
            json={
                "name": "Log run",
                "population_id": pop["id"],
                "main_ticks": [],
            },
        )
    ).json()
    started = await client.post(f"/runs/{run['id']}/start")
    assert started.status_code == 202
    await jobs_service._run_job(started.json()["job_id"])

    detail = await client.get(f"/runs/{run['id']}")
    attempt = detail.json()["results"]["attempts"][0]
    attempt_id = attempt["id"]
    variant_id = attempt["variants"][0]["id"]

    bad = await client.get(
        f"/runs/{run['id']}/logs",
        params={"attempt": attempt_id, "variant": "missing"},
    )
    assert bad.status_code == 404

    ok = await client.get(
        f"/runs/{run['id']}/logs",
        params={"attempt": attempt_id, "variant": variant_id, "tail": 20},
    )
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["run_id"] == run["id"]
    assert payload["attempt_id"] == attempt_id
    assert payload["variant_id"] == variant_id
    assert "engine=none" in payload["content"] or payload["content"]

