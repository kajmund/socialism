"""Workspace task instructions follow the Jev-exposed tool set."""

from app.services.prompt_catalog import default_prompts
from app.services.workspace_task_context import workspace_task_context


def test_find_context_contains_the_complete_find_show_contract():
    text = workspace_task_context(
        default_prompts("sv"),
        ["find_documents", "show_document_set"],
    )
    assert "find_documents" in text
    assert "show_document_set" in text
    assert "kapa aldrig sökresultatet" in text
    assert "focus_anchor" not in text


def test_task_context_only_contains_exposed_clusters():
    prompts = default_prompts("en")
    assert workspace_task_context(prompts, []) == ""
    text = workspace_task_context(prompts, ["focus_anchor"])
    assert "Highlight each requested passage" in text
    assert "find_documents" not in text


def test_split_reduces_always_on_workspace_prompt_size():
    prompts = default_prompts("sv")
    always_on = len(prompts["workspace.voice.system"]) + len(
        prompts["workspace.chat.turn"]
    )
    assert always_on < 2500
