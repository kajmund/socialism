"""Turn-local workspace instructions selected from Jev-exposed tools."""

from __future__ import annotations

from collections.abc import Iterable

from app.services.prompt_catalog import render_prompt

TASK_PREFIX = "workspace.voice.task."
TASK_CLUSTERS: tuple[tuple[str, frozenset[str]], ...] = (
    ("document_find", frozenset({"find_documents"})),
    (
        "document_locate",
        frozenset(
            {
                "get_workspace_context",
                "ingest_source",
                "search_knowledge",
                "read_source",
                "show_document",
            }
        ),
    ),
    ("document_mark", frozenset({"focus_anchor"})),
)


def workspace_task_context(prompts: dict[str, str], tool_names: Iterable[str]) -> str:
    """Render only task clusters represented in this turn's exposed tool set."""
    exposed = frozenset(tool_names)
    keys = [
        f"{TASK_PREFIX}{cluster}"
        for cluster, triggers in TASK_CLUSTERS
        if exposed & triggers
    ]
    return "\n\n".join(render_prompt(prompts, key) for key in keys)
