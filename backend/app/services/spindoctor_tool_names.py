"""Spinndoktor MCP tool name sets — no service imports (safe for MODULE_REGISTRY)."""

from __future__ import annotations

# OASIS / politik simulation data tools (implemented in spindoctor_tools.py).
SPINDOCTOR_OASIS_TOOL_NAMES = frozenset(
    {
        "get_test_message",
        "get_run",
        "search_reactions",
        "list_interviews",
        "list_actors",
        "get_citizen",
    }
)
