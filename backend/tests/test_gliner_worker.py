"""Subprocess lifecycle and worker-protocol tests for the GLiNER2 proposer."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.services.research.gliner import proposer
from app.services.research.gliner.proposer import (
    GlinerProposerError,
    ProposalUnit,
)


class FakeProcess:
    returncode: int | None = None


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


async def fake_spawn():
    return FakeProcess()


def fake_reply(payload: bytes) -> dict[str, object]:
    """Echo the request id like the real worker does."""
    request_id = json.loads(payload)["request_id"]
    return {
        "ok": True,
        "request_id": request_id,
        "result": [
            {"unit_id": "u1", "proposals": [{"span": "12 maj", "label": "Datum"}]}
        ],
    }


# ---------------------------------------------------------------- lifecycle


def test_proposer_spawns_worker_once(monkeypatch):
    spawns = {"count": 0}

    async def counting_spawn():
        spawns["count"] += 1
        return FakeProcess()

    async def fake_request(process, payload, timeout):
        return fake_reply(payload)

    monkeypatch.setattr(proposer, "_spawn_worker", counting_spawn)
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


def test_proposer_cancellation_kills_worker(monkeypatch):
    """A lost lease cancels the await; the worker must die so no stale reply
    can be consumed by the next request."""
    started = asyncio.Event()
    killed = {"count": 0}

    async def blocking_request(process, payload, timeout):
        started.set()
        await asyncio.sleep(60)

    async def fake_kill(process):
        killed["count"] += 1

    monkeypatch.setattr(proposer, "_spawn_worker", fake_spawn)
    monkeypatch.setattr(proposer, "_request", blocking_request)
    monkeypatch.setattr(proposer, "_kill_worker", fake_kill)
    proposer.reset_worker()

    async def run():
        task = asyncio.create_task(
            proposer.propose_spans((ProposalUnit(unit_id="u1", text="text"),), ("Datum",))
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert killed["count"] == 1


def test_proposer_rejects_stale_reply(monkeypatch):
    async def stale_request(process, payload, timeout):
        return {"ok": True, "request_id": "not-this-request", "result": []}

    killed = {"count": 0}

    async def fake_kill(process):
        killed["count"] += 1

    monkeypatch.setattr(proposer, "_spawn_worker", fake_spawn)
    monkeypatch.setattr(proposer, "_request", stale_request)
    monkeypatch.setattr(proposer, "_kill_worker", fake_kill)
    proposer.reset_worker()

    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer.propose_spans(
                (ProposalUnit(unit_id="u1", text="text"),), ("Datum",)
            )
        assert "stale" in str(excinfo.value)

    asyncio.run(run())
    assert killed["count"] == 1


def test_proposer_missing_dependencies(monkeypatch):
    async def failing_spawn():
        raise GlinerProposerError(
            "gliner_span_proposer is enabled but gliner2 is not installed",
            reason="missing_dependencies",
        )

    monkeypatch.setattr(proposer, "_spawn_worker", failing_spawn)
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


# ---------------------------------------------------------------- exit classes


def test_startup_exit_code_3_is_missing_dependencies():
    async def run():
        detail, reason = await proposer._worker_exit_detail(
            ExitProcess(3, b"ModuleNotFoundError: no module named gliner2"),
            phase="startup",
        )
        assert reason == "missing_dependencies"
        assert "gliner2" in detail

    asyncio.run(run())


def test_startup_other_exit_is_load_failure():
    async def run():
        _detail, reason = await proposer._worker_exit_detail(
            ExitProcess(1, b"RuntimeError: load failed"), phase="startup"
        )
        assert reason == "load_failed"

    asyncio.run(run())


def test_request_exit_is_inference_failure():
    async def run():
        _detail, reason = await proposer._worker_exit_detail(
            ExitProcess(1, b"RuntimeError: inference boom"), phase="request"
        )
        assert reason == "inference_failed"

    asyncio.run(run())


def test_spawn_eof_maps_exit_code_to_missing_dependencies(monkeypatch):
    class SpawnFailProcess:
        returncode = 3

        class stdout:
            @staticmethod
            async def readline() -> bytes:
                return b""

        class stderr:
            @staticmethod
            async def read() -> bytes:
                return b"ModuleNotFoundError: gliner2"

        def kill(self) -> None:
            pass

        async def wait(self) -> int:
            return 3

    async def fake_create(*args, **kwargs):
        return SpawnFailProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    proposer.reset_worker()

    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer._spawn_worker()
        assert excinfo.value.reason == "missing_dependencies"

    asyncio.run(run())


def test_request_eof_is_an_inference_failure(monkeypatch):
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

    async def fake_kill(process):
        pass

    monkeypatch.setattr(proposer, "_kill_worker", fake_kill)
    proposer.reset_worker()

    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer._request(
                StoppedProcess(1, b"Traceback: crashed"),
                b'{"unit_id": "x", "request_id": "r"}\n',
                5.0,
            )
        assert excinfo.value.reason == "inference_failed"
        assert "Traceback: crashed" in str(excinfo.value)

    asyncio.run(run())


# ---------------------------------------------------------------- worker protocol


def test_worker_handler_rejects_malformed_requests():
    from app.services.research.gliner import worker

    result = worker._handle_line(object(), "not json")
    assert result["reason"] == "invalid_request"


def test_worker_handler_uses_model_and_echoes_request_id():
    from app.services.research.gliner import worker

    class FakeModel:
        def extract_entities(self, text, **kwargs):
            return {"entities": [{"Datum": ["12 maj"]}]}

    result = worker._handle_line(
        FakeModel(),
        '{"request_id": "abc", "units": [{"unit_id": "u1", "text": "x"}], '
        '"labels": ["Datum"], "threshold": 0.3}',
    )
    assert result["ok"] is True
    assert result["request_id"] == "abc"
    assert result["result"][0]["proposals"] == [{"span": "12 maj", "label": "Datum"}]


# ---------------------------------------------------------------- atomic reset


class ManagedProcess:
    """A process whose ``wait()`` blocks until released."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.killed = False

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.returncode = 1
        return 1


def test_kill_worker_clears_handle_before_waiting():
    """The handle is cleared before the wait so a concurrent caller can never
    observe the dying worker as the current one."""
    released = asyncio.Event()
    started = asyncio.Event()

    class SlowProcess(ManagedProcess):
        async def wait(self) -> int:
            started.set()
            await released.wait()
            self.returncode = 1
            return 1

    process = SlowProcess()
    proposer.reset_worker()
    proposer._worker = process

    async def run():
        task = asyncio.create_task(proposer._kill_worker(process))
        await started.wait()
        assert proposer._worker is None  # cleared before wait completes
        released.set()
        await task

    asyncio.run(run())
    assert process.killed is True


def test_stale_reply_resets_worker_before_next_call(monkeypatch):
    """After a stale/mismatched reply the next call must spawn a fresh worker,
    not reuse the one being torn down."""
    spawns = {"count": 0}

    async def spawn():
        spawns["count"] += 1
        return ManagedProcess()

    async def request(process, payload, timeout):
        request_id = json.loads(payload)["request_id"]
        if spawns["count"] == 1:
            return {"ok": True, "request_id": "stale", "result": []}
        return {"ok": True, "request_id": request_id, "result": []}

    monkeypatch.setattr(proposer, "_spawn_worker", spawn)
    monkeypatch.setattr(proposer, "_request", request)
    proposer.reset_worker()

    async def run():
        with pytest.raises(GlinerProposerError):
            await proposer.propose_spans(
                (ProposalUnit(unit_id="u1", text="text"),), ("Datum",)
            )
        assert proposer._worker is None  # reset before the next caller
        result = await proposer.propose_spans(
            (ProposalUnit(unit_id="u1", text="text"),), ("Datum",)
        )
        assert result == []

    asyncio.run(run())
    assert spawns["count"] == 2  # a fresh worker, never the dying one
