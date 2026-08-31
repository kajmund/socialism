"""Tests for BolagsAPI MCP disk cache (10-month TTL)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.services.dd.bolagsapi_cache import (
    CACHE_TTL,
    cache_id,
    clear_bolagsapi_cache,
    get_cached,
    put_cached,
)
from app.services.dd.bolagsapi_mcp import BolagsapiMcpClient, BolagsapiMcpError


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "bolagsapi_cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "bolagsapi_api_key", "test-bolagsapi-key")
    clear_bolagsapi_cache()
    yield
    clear_bolagsapi_cache()


def test_cache_ttl_is_ten_months():
    assert CACHE_TTL == timedelta(days=304)


def test_put_and_get_within_ttl():
    now = datetime(2026, 8, 28, tzinfo=UTC)
    put_cached("call_tool", {"name": "search_companies", "query": "Spotify"}, "hit", now=now)
    assert get_cached("call_tool", {"name": "search_companies", "query": "Spotify"}, now=now) == "hit"


def test_expired_entry_is_a_miss():
    stored = datetime(2025, 1, 1, tzinfo=UTC)
    put_cached("call_tool", {"name": "search_companies", "query": "Spotify"}, "stale", now=stored)
    later = stored + CACHE_TTL + timedelta(seconds=1)
    assert get_cached("call_tool", {"name": "search_companies", "query": "Spotify"}, now=later) is None


def test_refuses_to_cache_rate_limit_text():
    with pytest.raises(ValueError, match="rate-limit"):
        put_cached("call_tool", {"name": "search_companies"}, "Rate limit exceeded")


def test_cache_id_is_stable_for_sorted_payloads():
    assert cache_id("call_tool", {"b": 1, "a": 2}) == cache_id("call_tool", {"a": 2, "b": 1})


def _sse(payload: dict) -> str:
    import json

    return f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@pytest.mark.asyncio
async def test_call_tool_serves_disk_cache_on_second_lookup(monkeypatch):
    posts: list[str] = []

    async def fake_post(self, payload: dict) -> tuple[int, str]:
        method = str(payload.get("method"))
        posts.append(method)
        if method == "initialize":
            return 200, _sse({"jsonrpc": "2.0", "result": {}})
        if method == "notifications/initialized":
            return 200, ""
        if method == "tools/call":
            return 200, _sse(
                {
                    "jsonrpc": "2.0",
                    "result": {
                        "content": [
                            {"type": "text", "text": "- **Spotify AB** [5567037485] - AB (STOCKHOLM)"}
                        ]
                    },
                }
            )
        raise AssertionError(method)

    monkeypatch.setattr(BolagsapiMcpClient, "_post", fake_post)

    async with BolagsapiMcpClient() as mcp:
        first = await mcp.call_tool("search_companies", {"query": "Spotify"})
        second = await mcp.call_tool("search_companies", {"query": "Spotify"})

    assert first == second
    assert first.startswith("- **Spotify AB**")
    assert posts == ["initialize", "notifications/initialized", "tools/call"]


@pytest.mark.asyncio
async def test_call_tool_does_not_cache_rate_limit(monkeypatch):
    async def fake_post(self, payload: dict) -> tuple[int, str]:
        method = str(payload.get("method"))
        if method == "initialize":
            return 200, _sse({"jsonrpc": "2.0", "result": {}})
        if method == "notifications/initialized":
            return 200, ""
        if method == "tools/call":
            return 200, _sse(
                {
                    "jsonrpc": "2.0",
                    "result": {"content": [{"type": "text", "text": "Rate limit exceeded"}]},
                }
            )
        raise AssertionError(method)

    monkeypatch.setattr(BolagsapiMcpClient, "_post", fake_post)

    async with BolagsapiMcpClient() as mcp:
        with pytest.raises(BolagsapiMcpError, match="rate limit"):
            await mcp.call_tool("search_companies", {"query": "Spotify"})

    assert get_cached("call_tool", {"url": settings.bolagsapi_mcp_url, "name": "search_companies", "arguments": {"query": "Spotify"}}) is None


@pytest.mark.asyncio
async def test_list_tools_uses_cache(monkeypatch):
    posts: list[str] = []
    tools = [{"name": "search_companies", "description": "Search", "inputSchema": {"type": "object"}}]

    async def fake_post(self, payload: dict) -> tuple[int, str]:
        method = str(payload.get("method"))
        posts.append(method)
        if method == "initialize":
            return 200, _sse({"jsonrpc": "2.0", "result": {}})
        if method == "notifications/initialized":
            return 200, ""
        if method == "tools/list":
            return 200, _sse({"jsonrpc": "2.0", "result": {"tools": tools}})
        raise AssertionError(method)

    monkeypatch.setattr(BolagsapiMcpClient, "_post", fake_post)

    async with BolagsapiMcpClient() as first:
        assert await first.list_tools() == tools
    async with BolagsapiMcpClient() as second:
        assert await second.list_tools() == tools

    assert posts == ["initialize", "notifications/initialized", "tools/list"]
