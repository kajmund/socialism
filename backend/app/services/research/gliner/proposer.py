"""Isolated GLiNER2 span proposer with a subprocess model lifecycle.

The model runs in a dedicated child process (``gliner.worker``), loaded once
per process and reused across runs. A timeout kills the process, so model
work actually stops — no lingering thread can keep inferring behind a
cancelled await, and a retry cannot overlap inference on the same model.
Requests are serialized through one worker; the heavy runtime dependencies
are never backend dependencies, and enabling the proposer without them fails
loudly (no fallback, no silent skip).
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass

from app.config import settings

GlinerProposerReason = (
    "missing_dependencies",
    "load_failed",
    "inference_failed",
    "timeout",
    "invalid_labels",
    "worker_failed",
)


class GlinerProposerError(Exception):
    """Typed proposer failure. Research treats this as fatal when enabled."""

    def __init__(self, message: str, *, reason: GlinerProposerReason) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ProposalUnit:
    """One bounded text unit the proposer may scan."""

    unit_id: str
    text: str


@dataclass(frozen=True)
class SpanProposal:
    span: str
    label: str


@dataclass(frozen=True)
class UnitProposals:
    unit_id: str
    proposals: tuple[SpanProposal, ...]


_worker: asyncio.subprocess.Process | None = None
_worker_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _worker_lock
    if _worker_lock is None:
        _worker_lock = asyncio.Lock()
    return _worker_lock


def _raise_worker_error(reason: str, detail: str) -> None:
    if reason == "missing_dependencies":
        raise GlinerProposerError(
            "gliner_span_proposer is enabled but gliner2 is not installed in "
            "the research runtime; install torch + transformers + gliner2",
            reason="missing_dependencies",
        )
    if reason == "load_failed":
        raise GlinerProposerError(
            f"failed to load GLiNER2 model {settings.gliner_span_proposer.model!r}: {detail}",
            reason="load_failed",
        )
    raise GlinerProposerError(
        f"GLiNER2 worker failed: {detail or reason}", reason="worker_failed"
    )


def _parse_line(line: bytes) -> dict[str, object]:
    if not line:
        return {"ok": False, "reason": "worker_failed", "error": "worker exited"}
    try:
        message = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "reason": "worker_failed", "error": str(exc)}
    return message if isinstance(message, dict) else {"ok": False, "reason": "worker_failed"}


async def _kill_worker(process: asyncio.subprocess.Process | None) -> None:
    global _worker
    if process is not None and process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
    if _worker is process:
        _worker = None


async def _spawn_worker() -> asyncio.subprocess.Process:
    """Start the worker process and wait for its ready line."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.services.research.gliner.worker",
        settings.gliner_span_proposer.model,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        line = await asyncio.wait_for(
            process.stdout.readline(),
            timeout=settings.gliner_span_proposer.inference_timeout_seconds,
        )
    except TimeoutError:
        await _kill_worker(process)
        raise GlinerProposerError(
            "GLiNER2 worker did not become ready in time", reason="load_failed"
        ) from None
    except asyncio.CancelledError:
        await asyncio.shield(_kill_worker(process))
        raise
    if not line:
        detail, reason = await _worker_exit_detail(process, phase="startup")
        await _kill_worker(process)
        raise GlinerProposerError(
            f"GLiNER2 worker failed to start: {detail or reason}", reason=reason
        )
    message = _parse_line(line)
    if not message.get("ok"):
        await _kill_worker(process)
        _raise_worker_error(
            str(message.get("reason") or "worker_failed"),
            str(message.get("error") or ""),
        )
    return process


async def _worker_exit_detail(
    process: asyncio.subprocess.Process, *, phase: str
) -> tuple[str, str]:
    """Read the worker's exit code and stderr tail; classify by the phase.

    Startup failures are missing dependencies (exit code 3) or a load
    failure. A worker that dies during a request is an inference failure.
    """
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        pass
    stderr = b""
    if process.stderr is not None:
        try:
            stderr = await asyncio.wait_for(process.stderr.read(), timeout=2)
        except TimeoutError:
            stderr = b""
    detail = stderr.decode("utf-8", "replace").strip()[-500:]
    if phase == "request":
        return detail, "inference_failed"
    if process.returncode == 3:
        return detail, "missing_dependencies"
    return detail, "load_failed"


async def _ensure_worker() -> asyncio.subprocess.Process:
    global _worker
    if _worker is not None and _worker.returncode is None:
        return _worker
    _worker = await _spawn_worker()
    return _worker


async def _request(
    process: asyncio.subprocess.Process,
    payload: bytes,
    timeout: float,
) -> dict[str, object]:
    """Send one request and read one reply. Caller holds the worker lock."""
    try:
        process.stdin.write(payload)  # type: ignore[union-attr]
        await process.stdin.drain()  # type: ignore[union-attr]
        line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout)  # type: ignore[union-attr]
    except (BrokenPipeError, ConnectionResetError):
        line = b""
    if not line:
        detail, reason = await _worker_exit_detail(process, phase="request")
        raise GlinerProposerError(
            f"GLiNER2 worker stopped: {detail or reason}", reason=reason
        )
    return _parse_line(line)


def reset_worker() -> None:
    """Test seam: forget the cached worker handle and lock."""
    global _worker, _worker_lock
    _worker = None
    _worker_lock = None


async def propose_spans(
    units: tuple[ProposalUnit, ...],
    labels: tuple[str, ...],
    *,
    timeout_seconds: float | None = None,
) -> list[UnitProposals]:
    """Propose spans for the given units. Fails loudly on any failure."""
    if not units:
        return []
    if not labels or any(not label.strip() for label in labels):
        raise GlinerProposerError(
            "propose_spans requires non-empty labels", reason="invalid_labels"
        )
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.gliner_span_proposer.inference_timeout_seconds
    )
    request_id = uuid.uuid4().hex
    payload = (
        json.dumps(
            {
                "request_id": request_id,
                "units": [{"unit_id": unit.unit_id, "text": unit.text} for unit in units],
                "labels": list(labels),
                "threshold": settings.gliner_span_proposer.threshold,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    process: asyncio.subprocess.Process | None = None
    async with _lock():
        process = await _ensure_worker()
        try:
            message = await _request(process, payload, timeout)
        except asyncio.CancelledError:
            # The lease was lost while the model worked: stop it and drop the
            # handle so no stale reply can be read by the next request.
            await asyncio.shield(_kill_worker(process))
            raise
        except TimeoutError:
            # Kill the process so the model work actually stops.
            await _kill_worker(process)
            raise GlinerProposerError(
                f"GLiNER2 inference timed out after {timeout:.0f}s",
                reason="timeout",
            ) from None
    if not message.get("ok") or str(message.get("request_id") or "") != request_id:
        await _kill_worker(process)
        if message.get("ok"):
            raise GlinerProposerError(
                "GLiNER2 worker replied to a stale request", reason="worker_failed"
            )
        _raise_worker_error(
            str(message.get("reason") or "worker_failed"),
            str(message.get("error") or ""),
        )
    result: list[UnitProposals] = []
    for entry in message.get("result", []):  # type: ignore[union-attr]
        proposals = tuple(
            SpanProposal(span=str(item["span"]), label=str(item["label"]))
            for item in entry.get("proposals", [])
        )
        result.append(UnitProposals(unit_id=str(entry["unit_id"]), proposals=proposals))
    return result
