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
    from typing import Any

    from app.llm import set_structured_completer
    from app.services.report.agent import SlotBatchResponse
    from app.services.report.classify import (
        _TopicBatchResponse,
        _TopicItem,
        _TopicPackModel,
        _TopicPacksResponse,
        _ToneBatchResponse,
        _ToneItem,
    )

    async def mock_llm(messages: list[dict[str, str]], response_model: type[Any]) -> Any:
        name = response_model.__name__
        if name == "_TopicPacksResponse":
            return _TopicPacksResponse(
                topics=[_TopicPackModel(label="Äldreomsorg", keywords=["äldreomsorg"])]
            )
        if name == "_TopicBatchResponse":
            user = messages[-1]["content"]
            n = sum(1 for line in user.splitlines() if line[:1].isdigit())
            return _TopicBatchResponse(
                items=[_TopicItem(index=i, topic="Äldreomsorg") for i in range(n)]
            )
        if name == "_ToneBatchResponse":
            user = messages[-1]["content"]
            n = sum(1 for line in user.splitlines() if line[:1].isdigit())
            system = next((m["content"] for m in messages if m.get("role") == "system"), "")
            tone = "Constructive" if "Allowed values" in system else "Konstruktiv"
            return _ToneBatchResponse(
                items=[_ToneItem(index=i, tone=tone) for i in range(n)]
            )
        if name == "SlotBatchResponse":
            content = messages[-1]["content"] if messages else ""
            slots: dict[str, str] = {}
            for line in content.splitlines():
                if line.startswith("- **") and "**:" in line:
                    slot = line.split("**")[1]
                    slots[slot] = f"text för {slot}"
            return SlotBatchResponse(slots=slots)
        raise AssertionError(f"Unexpected model {response_model}")

    set_structured_completer(mock_llm)
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
        assert body["job_id"]
        report_id = body["id"]

        await asyncio.wait_for(done.wait(), timeout=30)

        got = await client.get(f"/reports/{report_id}")
        assert got.status_code == 200
        data = got.json()
        assert data["status"] == "succeeded"
        assert data["html_path"]
        assert data["locale"] == "sv"

        html = await client.get(f"/reports/{report_id}/html")
        assert html.status_code == 200
        assert "text/html" in html.headers.get("content-type", "")
        assert "rapport.html" in html.headers.get("content-disposition", "")
        assert (
            b"donut" in html.content
            or b"info-kpi" in html.content
            or b"pyramid" in html.content
        )
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_create_english_report_locale(client, tmp_path, monkeypatch):
    from typing import Any

    from app.llm import set_structured_completer
    from app.services.report.agent import SlotBatchResponse
    from app.services.report.classify import (
        _TopicBatchResponse,
        _TopicItem,
        _TopicPackModel,
        _TopicPacksResponse,
        _ToneBatchResponse,
        _ToneItem,
    )

    async def mock_llm(messages: list[dict[str, str]], response_model: type[Any]) -> Any:
        name = response_model.__name__
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        english = "Answer in English" in system or "Classify each" in system or "You derive" in system
        if name == "_TopicPacksResponse":
            label = "Elder care" if english else "Äldreomsorg"
            return _TopicPacksResponse(
                topics=[_TopicPackModel(label=label, keywords=["care"])]
            )
        if name == "_TopicBatchResponse":
            user = messages[-1]["content"]
            n = sum(1 for line in user.splitlines() if line[:1].isdigit())
            topic = "Elder care" if english else "Äldreomsorg"
            return _TopicBatchResponse(
                items=[_TopicItem(index=i, topic=topic) for i in range(n)]
            )
        if name == "_ToneBatchResponse":
            user = messages[-1]["content"]
            n = sum(1 for line in user.splitlines() if line[:1].isdigit())
            tone = "Constructive" if english else "Konstruktiv"
            return _ToneBatchResponse(
                items=[_ToneItem(index=i, tone=tone) for i in range(n)]
            )
        if name == "SlotBatchResponse":
            content = messages[-1]["content"] if messages else ""
            slots: dict[str, str] = {}
            for line in content.splitlines():
                if line.startswith("- **") and "**:" in line:
                    slot = line.split("**")[1]
                    slots[slot] = f"text for {slot}"
            return SlotBatchResponse(slots=slots)
        raise AssertionError(f"Unexpected model {response_model}")

    set_structured_completer(mock_llm)
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
                "title": "My report",
                "locale": "en",
            },
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["locale"] == "en"
        report_id = body["id"]

        await asyncio.wait_for(done.wait(), timeout=30)

        got = (await client.get(f"/reports/{report_id}")).json()
        assert got["status"] == "succeeded"
        assert got["locale"] == "en"

        html = await client.get(f"/reports/{report_id}/html")
        assert html.status_code == 200
        assert "report.html" in html.headers.get("content-disposition", "")
        assert b'lang="en"' in html.content
        assert b"How the test worked" in html.content
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_english_report_uses_en_prompts_while_sv_active(
    client, tmp_path, monkeypatch
):
    """Report locale must select prompt language, not the globally active config."""
    from typing import Any

    from app.llm import set_structured_completer
    from app.services.report.agent import SlotBatchResponse
    from app.services.report.classify import (
        _TopicBatchResponse,
        _TopicItem,
        _TopicPackModel,
        _TopicPacksResponse,
        _ToneBatchResponse,
        _ToneItem,
    )

    captured_systems: list[str] = []

    async def mock_llm(messages: list[dict[str, str]], response_model: type[Any]) -> Any:
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        if system:
            captured_systems.append(system)
        name = response_model.__name__
        if name == "_TopicPacksResponse":
            return _TopicPacksResponse(
                topics=[_TopicPackModel(label="Elder care", keywords=["care"])]
            )
        if name == "_TopicBatchResponse":
            user = messages[-1]["content"]
            n = sum(1 for line in user.splitlines() if line[:1].isdigit())
            return _TopicBatchResponse(
                items=[_TopicItem(index=i, topic="Elder care") for i in range(n)]
            )
        if name == "_ToneBatchResponse":
            user = messages[-1]["content"]
            n = sum(1 for line in user.splitlines() if line[:1].isdigit())
            return _ToneBatchResponse(
                items=[_ToneItem(index=i, tone="Constructive") for i in range(n)]
            )
        if name == "SlotBatchResponse":
            return SlotBatchResponse(slots={"page_title": "My report"})
        raise AssertionError(f"Unexpected model {response_model}")

    configs = (await client.get("/configurations")).json()
    active = [c for c in configs if c["is_active"]]
    assert len(active) == 1
    assert active[0]["language"] == "sv"

    set_structured_completer(mock_llm)
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
                "title": "English prompts test",
                "locale": "en",
            },
        )
        assert resp.status_code == 202, resp.text
        await asyncio.wait_for(done.wait(), timeout=30)

        assert captured_systems
        assert any("Answer in English" in s for s in captured_systems)
        assert not any("Svara på svenska" in s for s in captured_systems)
    finally:
        set_structured_completer(None)

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
