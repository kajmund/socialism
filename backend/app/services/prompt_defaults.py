"""Module-owned prompt default lists for seed (Fas 3). Runtime still uses Configuration.prompts."""

from __future__ import annotations

from app.services.prompt_catalog import PROMPT_FIELDS, PromptFieldDef


def modules_for_prompt_key(key: str) -> list[str]:
    """Assign catalog keys to modules from the implicit prefix convention."""
    if key.startswith("panel.dd.") or key.startswith("dd."):
        return ["dd"]
    if (
        key.startswith("persona.")
        or key.startswith("messages.")
        or key.startswith("oasis.")
    ):
        return ["politik"]
    return ["dd", "politik"]


def prompt_defaults_for_module(module: str) -> list[PromptFieldDef]:
    return [field for field in PROMPT_FIELDS if module in modules_for_prompt_key(field["key"])]


def dd_prompt_defaults() -> list[PromptFieldDef]:
    return prompt_defaults_for_module("dd")


def politik_prompt_defaults() -> list[PromptFieldDef]:
    return prompt_defaults_for_module("politik")
