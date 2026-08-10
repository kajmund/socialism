#!/usr/bin/env python3
"""Opinionssimulator MCP server — OKF manuals + DeepSeek help + optional API tools."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from openai import OpenAI

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from integrations.okf.corpus import format_context, load_guides, search_guides

MANUAL_ROOT = Path(
    os.environ.get("OKF_MANUAL_ROOT", str(_REPO_ROOT / "knowledge" / "manual"))
)
API_URL = os.environ.get("OPINIONSSIMULATOR_API_URL", "").rstrip("/")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

server = Server("opinionssimulator")
_guides = load_guides(MANUAL_ROOT)


def _deepseek_client() -> OpenAI:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is required for ask_help")
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def _ask_help_sync(question: str, locale: str = "sv") -> str:
    hits = search_guides(_guides, question, limit=4)
    context = format_context(hits)
    language = "Swedish" if locale == "sv" else "English"
    system = (
        "You are the Opinionssimulator help assistant. Answer using the OKF operator "
        f"manual excerpts below. Be concise, friendly, and practical. Reply in {language}. "
        "If the manuals do not cover the question, say so and suggest where in the admin UI "
        "the user might look (Körningar, Personas, Populationer, Budskap, Verktyg, Jobb). "
        "Do not invent features that are not described in the manuals.\n\n"
        f"# Manual excerpts\n\n{context}"
    )
    client = _deepseek_client()
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
    )
    return (response.choices[0].message.content or "").strip()


async def _api_get(path: str) -> object:
    if not API_URL:
        raise RuntimeError(
            "OPINIONSSIMULATOR_API_URL is not set — start the backend or omit API tools"
        )
    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        response = await client.get(path)
        response.raise_for_status()
        return response.json()


@server.list_tools()
async def list_tools() -> list[Tool]:
    tools = [
        Tool(
            name="okf_search",
            description="Search Opinionssimulator OKF operator manuals by keyword.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="okf_get_guide",
            description="Fetch one OKF guide by slug (filename without .md).",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Guide slug, e.g. skapa-korning",
                    }
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="ask_help",
            description=(
                "Answer a help question about Opinionssimulator using OKF manuals + DeepSeek."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "locale": {
                        "type": "string",
                        "enum": ["sv", "en"],
                        "default": "sv",
                    },
                },
                "required": ["question"],
            },
        ),
    ]
    if API_URL:
        tools.extend(
            [
                Tool(
                    name="list_runs",
                    description="List körningar from the Opinionssimulator API.",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="get_run",
                    description="Fetch one körning by id.",
                    inputSchema={
                        "type": "object",
                        "properties": {"run_id": {"type": "integer"}},
                        "required": ["run_id"],
                    },
                ),
            ]
        )
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "okf_search":
        query = str(arguments.get("query", "")).strip()
        limit = int(arguments.get("limit") or 5)
        hits = search_guides(_guides, query, limit=max(1, min(limit, 10)))
        payload = [
            {
                "slug": g.slug,
                "title": g.title,
                "description": g.description,
                "tags": list(g.tags),
            }
            for g in hits
        ]
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    if name == "okf_get_guide":
        slug = str(arguments.get("slug", "")).strip()
        guide = next((g for g in _guides if g.slug == slug), None)
        if guide is None:
            return [TextContent(type="text", text=f"Guide not found: {slug}")]
        return [TextContent(type="text", text=guide.text)]

    if name == "ask_help":
        question = str(arguments.get("question", "")).strip()
        if not question:
            return [TextContent(type="text", text="question is required")]
        locale = str(arguments.get("locale") or "sv")
        answer = await asyncio.to_thread(_ask_help_sync, question, locale)
        return [TextContent(type="text", text=answer)]

    if name == "list_runs":
        data = await _api_get("/runs")
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

    if name == "get_run":
        run_id = int(arguments["run_id"])
        data = await _api_get(f"/runs/{run_id}")
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
