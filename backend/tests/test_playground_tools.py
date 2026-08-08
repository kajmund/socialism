"""Playground agent-tool catalog and run endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.playground_tools import list_tool_catalog, run_agent_tool


def test_list_tool_catalog_includes_search():
    catalog = list_tool_catalog()
    families = {f["id"]: f for f in catalog["families"]}
    assert "web_search" in families
    names = {t["name"] for t in families["web_search"]["tools"]}
    assert names == {"search_duckduckgo", "search_wiki"}
    assert "sympy" in families


def test_run_search_wiki_mocked():
    with patch(
        "app.services.playground_tools.search_wiki",
        return_value="Sammanfattning om test.",
    ):
        out = run_agent_tool("search_wiki", {"entity": "Test"})
    assert out["error"] is None
    assert out["result"] == "Sammanfattning om test."
    assert out["elapsed_ms"] >= 0


def test_run_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        run_agent_tool("not_a_real_tool", {})


@pytest.mark.asyncio
async def test_tools_catalog_api(client):
    res = await client.get("/playground/tools/catalog")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["families"]


@pytest.mark.asyncio
async def test_tools_run_api_mocked(client):
    with patch(
        "app.services.playground_tools.search_duckduckgo",
        return_value=[{"result_id": 1, "title": "T", "description": "D", "url": "u"}],
    ):
        res = await client.post(
            "/playground/tools/run",
            json={
                "tool_name": "search_duckduckgo",
                "arguments": {"query": "norrköping", "number_of_result_pages": 3},
            },
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["error"] is None
    assert body["result"][0]["title"] == "T"


@pytest.mark.asyncio
async def test_tools_run_unknown_api(client):
    res = await client.post(
        "/playground/tools/run",
        json={"tool_name": "nope", "arguments": {}},
    )
    assert res.status_code == 400
