"""Unit tests for SCB PxWebApi client and tools (mocked HTTP)."""

from __future__ import annotations

import json

import httpx
import pytest
from integrations.scb.client import ScbClient
from integrations.scb.tools import help_scb_tool_specs, run_scb_tool


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


def test_help_scb_tool_specs_always_includes_population_dist():
    names = {spec["function"]["name"] for spec in help_scb_tool_specs(allow_population_dist=False)}
    assert "scb_population_dist" in names
    assert "scb_get_table_meta" in names


@pytest.mark.asyncio
async def test_run_scb_tool_population_dist_allowed_without_opt_in():
    class FakeClient:
        async def get_table_meta(self, table_id: str, *, lang: str = "sv"):
            return {
                "dimension": {
                    "Region": {"category": {"label": {"0581": "Norrköping"}}},
                }
            }

        async def query(self, table_id: str, filters, *, lang: str = "sv"):
            raise AssertionError("should resolve via find_region_code then fetch_population_distribution")

    # allow_population_dist=False must not block (compat no-op)
    result = await run_scb_tool(
        "scb_population_dist",
        {"region_name": "UnknownPlaceXYZ"},
        client=FakeClient(),  # type: ignore[arg-type]
        allow_population_dist=False,
    )
    assert "Could not resolve municipality" in result


@pytest.mark.asyncio
async def test_get_table_meta_filters_variable_and_omits_large_code_maps():
    large_labels = {str(i): f"Region {i}" for i in range(50)}
    small_labels = {"OG": "Ogift", "G": "Gift"}

    class FakeClient:
        async def get_table_meta(self, table_id: str, *, lang: str = "sv"):
            assert table_id == "TAB6570"
            return {
                "label": "Folkmängd",
                "updated": "2024-01-01",
                "dimension": {
                    "Region": {"label": "region", "category": {"label": large_labels}},
                    "Civilstand": {"label": "civilstånd", "category": {"label": small_labels}},
                },
            }

    overview = await run_scb_tool(
        "scb_get_table_meta",
        {"table_id": "TAB6570"},
        client=FakeClient(),  # type: ignore[arg-type]
    )
    parsed = json.loads(overview)
    assert "codes" not in parsed["variables"]["Region"]
    assert parsed["variables"]["Region"]["code_count"] == 50
    assert parsed["variables"]["Civilstand"]["codes"] == small_labels

    filtered = await run_scb_tool(
        "scb_get_table_meta",
        {"table_id": "TAB6570", "variable": "Civilstand"},
        client=FakeClient(),  # type: ignore[arg-type]
    )
    one = json.loads(filtered)
    assert list(one["variables"].keys()) == ["Civilstand"]
    assert one["variables"]["Civilstand"]["codes"] == small_labels

    missing = await run_scb_tool(
        "scb_get_table_meta",
        {"table_id": "TAB6570", "variable": "Nope"},
        client=FakeClient(),  # type: ignore[arg-type]
    )
    assert "not found" in missing
    assert "Civilstand" in missing
