"""Unit tests for SCB PxWebApi client and tools (mocked HTTP)."""

from __future__ import annotations

import json

import httpx
import pytest
from integrations.scb.client import ScbClient
from integrations.scb.tools import run_scb_tool


@pytest.mark.asyncio
async def test_search_tables_parses_response():
    payload = {
        "language": "sv",
        "tables": [{"id": "TAB638", "label": "Folkmängd", "variableNames": ["region"]}],
        "page": {"totalElements": 1},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/tables")
        assert request.url.params.get("query") == "folkmängd"
        return httpx.Response(200, json=payload)

    client = ScbClient()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=client._base_url) as http:
        async def patched_get(path: str, *, params=None):
            response = await http.get(path, params=params)
            response.raise_for_status()
            return response.json()

        client._get = patched_get  # type: ignore[method-assign]
        data = await client.search_tables("folkmängd")
        assert data["tables"][0]["id"] == "TAB638"


@pytest.mark.asyncio
async def test_run_scb_tool_search_tables():
    payload = {
        "tables": [{"id": "TAB638", "label": "Folkmängd", "variableNames": ["region"]}],
        "page": {"totalElements": 1},
    }

    class FakeClient:
        async def search_tables(self, query: str, *, page_size: int = 10):
            assert query == "folkmängd"
            return payload

    text = await run_scb_tool("scb_search_tables", {"query": "folkmängd"}, client=FakeClient())  # type: ignore[arg-type]
    parsed = json.loads(text)
    assert parsed["tables"][0]["id"] == "TAB638"


@pytest.mark.asyncio
async def test_run_scb_tool_query_requires_filters():
    result = await run_scb_tool("scb_query", {"table_id": "TAB638", "filters": []})
    assert "non-empty" in result
