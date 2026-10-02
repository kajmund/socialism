"""Opt-in, measured 429 backoff for the frozen-input experiment only."""

import math
import random
import time
from asyncio import sleep
from email.utils import parsedate_to_datetime

import httpx

from app.jev.system import JevClientError
from tests.research_reuse.jev_diagnostics import DiagnosticJev
from tests.research_reuse.snapshots import digest

POLICY = {"max_attempts": 4, "base_delay_seconds": 0.5,
    "jitter_seconds": 0.2, "max_wait_seconds_per_request": 20.0}


def retry_delay(response: httpx.Response, attempt: int) -> float:
    delay = POLICY["base_delay_seconds"] * 2 ** (attempt - 1) + random.uniform(0, POLICY["jitter_seconds"])
    header = response.headers.get("retry-after")
    if header is None:
        return delay
    try:
        seconds = float(header)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(header).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError) as exc:
            raise JevClientError("Invalid Jev Retry-After header", category="rate_limit") from exc
    if not math.isfinite(seconds):
        raise JevClientError("Invalid Jev Retry-After header", category="rate_limit")
    return max(delay, seconds)


class BackoffJev(DiagnosticJev):
    def __init__(self) -> None:
        super().__init__()
        self.paused_until = 0.0
        self.attempts: list[dict] = []
        self.waits: list[dict] = []
        self.retries: list[dict] = []

    async def _wait(self, request_sha256: str, remaining: float) -> float:
        waited = 0.0
        while (delay := self.paused_until - time.monotonic()) > 0:
            if delay > remaining - waited:
                raise JevClientError("Jev 429 backoff wait budget exhausted", category="rate_limit")
            started = time.monotonic()
            row = {"request_sha256": request_sha256, "planned_seconds": delay, "seconds": 0.0}
            self.waits.append(row)
            try:
                await sleep(delay)
            finally:
                row["seconds"] = time.monotonic() - started
                waited += row["seconds"]
        return waited

    async def _attempt(self, body: dict, api_key: str, timeout_seconds: float, row: dict) -> httpx.Response:
        self.attempts.append(row)
        started = time.monotonic()
        try:
            response = await super()._post(body, api_key, timeout_seconds)
            row.update(status="completed", http_status=response.status_code)
            return response
        finally:
            row["seconds"] = time.monotonic() - started

    async def _post(self, body: dict, api_key: str, timeout_seconds: float) -> httpx.Response:
        request_sha256 = digest(body)
        waited = 0.0
        for attempt in range(1, POLICY["max_attempts"] + 1):
            waited += await self._wait(request_sha256, POLICY["max_wait_seconds_per_request"] - waited)
            row = {"request_sha256": request_sha256, "attempt": attempt, "status": "incomplete"}
            response = await self._attempt(body, api_key, timeout_seconds, row)
            if response.status_code != 429 or attempt == POLICY["max_attempts"]:
                return response
            delay = retry_delay(response, attempt)
            self.retries.append({"request_sha256": request_sha256, "after_attempt": attempt,
                "delay_seconds": delay, "retry_after": response.headers.get("retry-after")})
            self.paused_until = max(self.paused_until, time.monotonic() + delay)
        raise AssertionError("Attempt limit must return a response")
