"""Run OASIS agent tools directly for playground calibration (no full sim)."""

from __future__ import annotations

import inspect
import time
import types
from typing import Any, Literal

from app.schemas.domain import OasisRunOptions
from app.services.oasis_agent_tools import (
    build_population_extra_tools,
    search_duckduckgo,
    search_wiki,
)

ToolFamily = Literal["web_search", "sympy"]

_UNWRAPPED_CALLABLE = (
    types.FunctionType,
    types.MethodType,
    types.BuiltinFunctionType,
)


def _tool_callable(tool: Any) -> Any:
    """Prefer CAMEL FunctionTool.func; otherwise the tool itself if callable."""
    fn = getattr(tool, "func", None)
    if isinstance(fn, _UNWRAPPED_CALLABLE):
        return fn
    if callable(tool):
        return tool
    label = getattr(tool, "__name__", None)
    if not isinstance(label, str) or not label:
        label = type(tool).__name__
    raise TypeError(f"Tool {label} is not callable")


def _callable_name(tool: Any) -> str:
    fn = _tool_callable(tool)
    name = getattr(fn, "__name__", None)
    if isinstance(name, str) and name:
        return name
    return str(getattr(tool, "name", type(fn).__name__))


def _callable_doc(tool: Any) -> str:
    fn = _tool_callable(tool)
    doc = getattr(fn, "__doc__", None)
    if isinstance(doc, str):
        return inspect.cleandoc(doc).strip()
    return ""


def _openai_params(tool: Any) -> dict[str, Any]:
    if hasattr(tool, "get_openai_tool_schema"):
        schema = tool.get_openai_tool_schema()
        return schema.get("function", {}).get("parameters", {}) or {}
    fn = _tool_callable(tool)
    sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in {"self", "cls"}:
            continue
        props[name] = {"type": "string"}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def _invoke_tool(tool: Any, arguments: dict[str, Any]) -> Any:
    return _tool_callable(tool)(**arguments)


def list_tool_catalog() -> dict[str, Any]:
    """Catalog of tools agents can get via oasis_options (for playground UI)."""
    search_tools = [
        {
            "name": "search_duckduckgo",
            "family": "web_search",
            "description": _callable_doc(search_duckduckgo),
            "parameters": _openai_params(search_duckduckgo),
        },
        {
            "name": "search_wiki",
            "family": "web_search",
            "description": _callable_doc(search_wiki),
            "parameters": _openai_params(search_wiki),
        },
    ]
    sympy_tools: list[dict[str, Any]] = []
    try:
        raw = build_population_extra_tools(
            OasisRunOptions(enable_sympy_tools=True)
        )
    except Exception as exc:  # noqa: BLE001 — surface missing oasis extra clearly
        sympy_error = str(exc) or exc.__class__.__name__
        raw = []
    else:
        sympy_error = None
        for tool in raw:
            sympy_tools.append(
                {
                    "name": _callable_name(tool),
                    "family": "sympy",
                    "description": _callable_doc(tool),
                    "parameters": _openai_params(tool),
                }
            )

    return {
        "families": [
            {
                "id": "web_search",
                "label": "Webbsök",
                "tools": search_tools,
            },
            {
                "id": "sympy",
                "label": "SymPy",
                "tools": sympy_tools,
                "unavailable_reason": sympy_error,
            },
        ]
    }


def _resolve_tool(tool_name: str) -> Any:
    name = (tool_name or "").strip()
    if not name:
        raise ValueError("tool_name is required")
    if name == "search_duckduckgo":
        return search_duckduckgo
    if name == "search_wiki":
        return search_wiki
    tools = build_population_extra_tools(OasisRunOptions(enable_sympy_tools=True))
    for tool in tools:
        if _callable_name(tool) == name:
            return tool
    known = sorted(
        {"search_duckduckgo", "search_wiki", *(_callable_name(t) for t in tools)}
    )
    raise ValueError(f"Unknown tool {name!r}. Known: {', '.join(known)}")


def run_agent_tool(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke one agent tool; returns result + timing. Failures surface in result."""
    args = dict(arguments or {})
    tool = _resolve_tool(tool_name)
    t0 = time.perf_counter()
    try:
        result = _invoke_tool(tool, args)
        error = None
    except TypeError as exc:
        result = None
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 — playground should show tool errors
        result = None
        error = str(exc) or exc.__class__.__name__
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "tool_name": _callable_name(tool),
        "arguments": args,
        "result": result,
        "error": error,
        "elapsed_ms": elapsed_ms,
    }
