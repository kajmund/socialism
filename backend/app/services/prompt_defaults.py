"""Module-owned prompt default lists for seed. Runtime reads prompt_fields + prompt_overrides."""

from __future__ import annotations

from app.services.prompt_catalog import PROMPT_FIELDS, PromptFieldDef


def modules_for_prompt_key(key: str) -> list[str]:
    """Assign catalog keys to modules from the implicit prefix convention."""
    if key.startswith(("panel.dd.", "dd.")):
        return ["dd"]
    if key.startswith(("persona.", "messages.", "oasis.")):
        return ["politik"]
    if key.startswith("help."):
        return ["dd", "politik"]
    return ["dd", "politik", "expertgranskning"]


def prompt_defaults_for_module(module: str) -> list[PromptFieldDef]:
    return [field for field in PROMPT_FIELDS if module in modules_for_prompt_key(field["key"])]


def dd_prompt_defaults() -> list[PromptFieldDef]:
    return prompt_defaults_for_module("dd")


def politik_prompt_defaults() -> list[PromptFieldDef]:
    return prompt_defaults_for_module("politik")


def expertgranskning_prompt_defaults() -> list[PromptFieldDef]:
    return prompt_defaults_for_module("expertgranskning")
