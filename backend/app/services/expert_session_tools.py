"""OpenAI tool specs for expert research, evidence lookup, and colleague consult."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

RESEARCH_TOOL_NAME = "start_research"
EVIDENCE_TOOL_NAME = "lookup_research_evidence"
CONSULT_TOOL_NAME = "ask_expert"
ResearchToolHandler = Callable[[dict[str, Any]], Awaitable[str]]
EvidenceToolHandler = Callable[[dict[str, Any]], Awaitable[str]]
ConsultToolHandler = Callable[[dict[str, Any]], Awaitable[str]]

RESEARCH_TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RESEARCH_TOOL_NAME,
        "description": (
            "Queue background research when the user wants something investigated. "
            "Call it in the same turn. Do not ask for a separate approval first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Standalone general research question",
                }
            },
            "required": ["question"],
        },
    },
}

EVIDENCE_TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": EVIDENCE_TOOL_NAME,
        "description": (
            "Look up previously frozen research evidence that matches a question. "
            "Does not start new research."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Standalone question to match against frozen research",
                }
            },
            "required": ["question"],
        },
    },
}

CONSULT_TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": CONSULT_TOOL_NAME,
        "description": (
            "Ask a competent colleague when the question is outside your own "
            "professional competence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Standalone question for the colleague",
                }
            },
            "required": ["question"],
        },
    },
}


def research_tool_spec() -> dict[str, Any]:
    return dict(RESEARCH_TOOL_SPEC)


def evidence_tool_spec() -> dict[str, Any]:
    return dict(EVIDENCE_TOOL_SPEC)


def consult_tool_spec() -> dict[str, Any]:
    return dict(CONSULT_TOOL_SPEC)
