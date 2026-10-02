import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import settings
from app.jev.system import JevClientError
from tests.research_reuse import jev_backoff as backoff
from tests.research_reuse.jev_diagnostics import DiagnosticJev

pytestmark = pytest.mark.research_reuse
BODY = {"model": "fixed", "state": {"excerpt": "Åäö\r\n whole source"},
    "questions": {"q": {"type": "boolean"}}}


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(backoff.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(backoff.time, "time", lambda: now[0])
    monkeypatch.setattr(backoff, "sleep", sleep)
    monkeypatch.setattr(backoff.random, "uniform", lambda *_: 0.0)
    return now


def gateway(monkeypatch, responses):
    external = AsyncMock(side_effect=responses)
    monkeypatch.setattr(DiagnosticJev, "_post", external)
    return external


async def test_429_retries_exact_payload_and_records_wait_and_physical_attempts(monkeypatch, clock):
    external = gateway(monkeypatch, [httpx.Response(429), httpx.Response(200)])
    client = backoff.BackoffJev()
    result = await client._post(BODY, "secret", 5.0)
    assert result.status_code == 200
    assert external.await_count == 2
    assert all(call.args == (BODY, "secret", 5.0) for call in external.await_args_list)
    assert [a["http_status"] for a in client.attempts] == [429, 200]
    assert client.waits[0]["seconds"] == 0.5
    assert client.retries[0]["delay_seconds"] == 0.5
    assert len({a["request_sha256"] for a in client.attempts}) == 1
    assert "secret" not in str(client.attempts + client.waits + client.retries)


async def test_attempt_limit_returns_429_for_existing_error_parser(monkeypatch, clock):
    external = gateway(monkeypatch, [httpx.Response(429)] * 4)
    client = backoff.BackoffJev()
    result = await client._post(BODY, "secret", 5.0)
    assert result.status_code == 429 and external.await_count == 4
    assert [r["delay_seconds"] for r in client.retries] == [0.5, 1.0, 2.0]
    assert sum(w["seconds"] for w in client.waits) == 3.5


@pytest.mark.parametrize("status", [400, 401, 403, 500, 503])
async def test_only_429_is_retried(monkeypatch, clock, status):
    external = gateway(monkeypatch, [httpx.Response(status)])
    client = backoff.BackoffJev()
    assert (await client._post(BODY, "secret", 5.0)).status_code == status
    assert external.await_count == 1 and not client.waits


async def test_timeout_propagates_without_retry(monkeypatch, clock):
    external = gateway(monkeypatch, [httpx.ReadTimeout("timeout")])
    client = backoff.BackoffJev()
    with pytest.raises(httpx.ReadTimeout):
        await client._post(BODY, "secret", 5.0)
    assert external.await_count == 1 and not client.retries
    assert client.attempts[0]["status"] == "incomplete"


@pytest.mark.parametrize("header", ["2", format_datetime(datetime.fromtimestamp(2, timezone.utc), usegmt=True)])
async def test_retry_after_minimum_is_respected(monkeypatch, clock, header):
    gateway(monkeypatch, [httpx.Response(429, headers={"Retry-After": header}), httpx.Response(200)])
    client = backoff.BackoffJev()
    await client._post(BODY, "secret", 5.0)
    assert client.waits[0]["seconds"] == 2.0


async def test_long_retry_after_fails_without_retrying_earlier(monkeypatch, clock):
    external = gateway(monkeypatch, [httpx.Response(429, headers={"Retry-After": "60"})])
    client = backoff.BackoffJev()
    with pytest.raises(JevClientError, match="budget exhausted") as error:
        await client._post(BODY, "secret", 5.0)
    assert error.value.category == "rate_limit"
    assert external.await_count == 1 and not client.waits


async def test_cumulative_wait_budget_is_bounded(monkeypatch, clock):
    external = gateway(monkeypatch, [httpx.Response(429, headers={"Retry-After": "7"})] * 3)
    client = backoff.BackoffJev()
    with pytest.raises(JevClientError, match="budget exhausted"):
        await client._post(BODY, "secret", 5.0)
    assert external.await_count == 3
    assert sum(w["seconds"] for w in client.waits) == 14.0


@pytest.mark.parametrize("header", ["nonsense", "nan", "inf"])
def test_invalid_retry_after_fails_loudly(clock, header):
    with pytest.raises(JevClientError, match="Invalid"):
        backoff.retry_delay(httpx.Response(429, headers={"Retry-After": header}), 1)


async def test_shared_pause_blocks_new_requests_and_cancellation_stops_wait(monkeypatch):
    external = gateway(monkeypatch, [httpx.Response(200)])
    waiting = asyncio.Event()

    async def sleep(_seconds):
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(backoff, "sleep", sleep)
    client = backoff.BackoffJev()
    client.paused_until = backoff.time.monotonic() + 0.5
    task = asyncio.create_task(client._post(BODY, "secret", 5.0))
    await waiting.wait()
    assert not external.called
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not external.called and len(client.waits) == 1


async def test_ask_latency_includes_backoff(monkeypatch, clock):
    monkeypatch.setattr(settings, "typesafe_api_key", "secret")
    monkeypatch.setattr(backoff.time, "perf_counter", lambda: clock[0])
    gateway(monkeypatch, [httpx.Response(429), httpx.Response(200,
        json={"model": "fixed", "answers": {"q": {"noul": 0.9}}})])
    result = await backoff.BackoffJev().ask(**BODY, timeout_seconds=5.0)
    assert result.latency_ms == 500.0 and result.model == "fixed"
