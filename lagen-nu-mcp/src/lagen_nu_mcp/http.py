"""Polite HTTP client for lagen.nu (identifying User-Agent + min interval)."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status: int
    content_type: str
    body: str


@dataclass
class RateLimiter:
    min_interval_seconds: float
    _last: float = field(default=0.0, init=False)

    def wait(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        now = time.monotonic()
        delay = self.min_interval_seconds - (now - self._last)
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


class HttpClient:
    def __init__(self, *, user_agent: str, limiter: RateLimiter, timeout: float = 60.0):
        self.user_agent = user_agent
        self.limiter = limiter
        self.timeout = timeout

    def get(self, url: str, *, accept: str) -> HttpResponse:
        self.limiter.wait()
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": accept,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                content_type = response.headers.get_content_type()
                status = response.status
                final_url = response.geturl()
        except urllib.error.HTTPError as exc:
            raise FetchError(f"GET {url} failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise FetchError(f"GET {url} failed: {exc.reason}") from exc
        return HttpResponse(
            url=final_url,
            status=status,
            content_type=content_type,
            body=body.decode("utf-8"),
        )

    def get_text(self, url: str, *, accept: str) -> str:
        return self.get(url, accept=accept).body
