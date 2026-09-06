import time

from lagen_nu_mcp.http import RateLimiter


def test_rate_limiter_enforces_min_interval() -> None:
    limiter = RateLimiter(0.05)
    limiter.wait()
    started = time.monotonic()
    limiter.wait()
    elapsed = time.monotonic() - started
    assert elapsed >= 0.04
