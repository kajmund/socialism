"""Subprocess lifecycle and worker-protocol tests for the GLiNER2 proposer."""

from __future__ import annotations

import asyncio

import pytest

from app.services.research.gliner import proposer
from app.services.research.gliner.proposer import (
    GlinerProposerError,
    ProposalUnit,
)


class FakeProcess:
    returncode: int | None = None


# ---------------------------------------------------------------- proposer


def test_proposer_spawns_worker_once(monkeypatch):
    spawns = {"count": 0}

    async def fake_spawn():
        spawns["count"] += 1
        return FakeProcess()

    async def fake_request(process, payload, timeout):
        return {
            "ok": True,
            "result": [
                {"unit_id": "u1", "proposals": [{"span": "12 maj", "label": "Datum"}]}
            ],
        }

    monkeypatch.setattr(proposer, "_spawn_worker", fake_spawn)
    monkeypatch.setattr(proposer, "_request", fake_request)
    proposer.reset_worker()

    async def run():
        first = await proposer.propose_spans(
            (ProposalUnit(unit_id="u1", text="text"),), ("Datum",)
        )
        second = await proposer.propose_spans(
            (ProposalUnit(unit_id="u1", text="text"),), ("Datum",)
        )
        return first, second

    first, second = asyncio.run(run())
    assert spawns["count"] == 1
    assert first[0].proposals[0].span == "12 maj"
    assert second[0].proposals[0].span == "12 maj"


def test_proposer_timeout_kills_worker(monkeypatch):
    killed = {"ok": False}

    async def fake_spawn():
        return FakeProcess()

    async def fake_request(process, payload, timeout):
        raise TimeoutError

    async def fake_kill(process):
        killed["ok"] = True

    monkeypatch.setattr(proposer, "_spawn_worker", fake_spawn)
    monkeypatch.setattr(proposer, "_request", fake_request)
    monkeypatch.setattr(proposer, "_kill_worker", fake_kill)
    proposer.reset_worker()

    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer.propose_spans(
                (ProposalUnit(unit_id="u1", text="text"),),
                ("Datum",),
                timeout_seconds=0.01,
            )
        assert excinfo.value.reason == "timeout"

    asyncio.run(run())
    assert killed["ok"] is True


def test_proposer_missing_dependencies(monkeypatch):
    async def fake_spawn():
        raise GlinerProposerError(
            "gliner_span_proposer is enabled but gliner2 is not installed",
            reason="missing_dependencies",
        )

    monkeypatch.setattr(proposer, "_spawn_worker", fake_spawn)
    proposer.reset_worker()

    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer.propose_spans(
                (ProposalUnit(unit_id="u1", text="text"),), ("Datum",)
            )
        assert excinfo.value.reason == "missing_dependencies"

    asyncio.run(run())


def test_proposer_invalid_labels():
    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer.propose_spans(
                (ProposalUnit(unit_id="u1", text="text"),), ()
            )
        assert excinfo.value.reason == "invalid_labels"
        assert await proposer.propose_spans((), ("Datum",)) == []

    asyncio.run(run())




# ---------------------------------------------------------------- worker protocol


class FakeReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def read(self) -> bytes:
        return self.payload


class ExitProcess:
    def __init__(self, returncode: int, stderr: bytes) -> None:
        self.returncode = returncode
        self.stderr = FakeReader(stderr)

    async def wait(self) -> int:
        return self.returncode


def test_worker_exit_code_maps_to_typed_reason():
    async def run():
        detail, reason = await proposer._worker_exit_detail(
            ExitProcess(3, b"ModuleNotFoundError: no module named gliner2")
        )
        assert reason == "missing_dependencies"
        assert "gliner2" in detail
        _detail, reason = await proposer._worker_exit_detail(
            ExitProcess(1, b"RuntimeError: load failed")
        )
        assert reason == "load_failed"

    asyncio.run(run())


def test_worker_request_eof_is_a_typed_worker_failure(monkeypatch):
    class StoppedProcess(ExitProcess):
        class stdin:
            @staticmethod
            def write(payload: bytes) -> None:
                pass

            @staticmethod
            async def drain() -> None:
                pass

        class stdout:
            @staticmethod
            async def readline() -> bytes:
                return b""

    proposer.reset_worker()

    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer._request(
                StoppedProcess(1, b"Traceback: crashed"),
                b'{"units": [], "labels": []}\n',
                5.0,
            )
        assert excinfo.value.reason == "worker_failed"
        assert "Traceback: crashed" in str(excinfo.value)

    asyncio.run(run())


def test_worker_handler_rejects_malformed_requests():
    from app.services.research.gliner import worker

    result = worker._handle_line(object(), "not json")
    assert result["reason"] == "invalid_request"


def test_worker_handler_uses_model(monkeypatch):
    from app.services.research.gliner import worker

    class FakeModel:
        def extract_entities(self, text, **kwargs):
            return {"entities": [{"Datum": ["12 maj"]}]}

    result = worker._handle_line(FakeModel(), '{"units": [{"unit_id": "u1", "text": "x"}], "labels": ["Datum"], "threshold": 0.3}')
    assert result["ok"] is True
    assert result["result"][0]["proposals"] == [{"span": "12 maj", "label": "Datum"}]
