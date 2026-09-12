"""Operator review intent prepended to panel and Word-review briefs."""

from __future__ import annotations

from app.services.panel.schemas import PanelSessionConfig
from app.services.prompt_catalog import render_prompt


def render_review_intent_message(prompts: dict[str, str], review_intent: str) -> str:
    text = (review_intent or "").strip()
    if not text:
        return ""
    sentinel = "\0REVIEW_INTENT\0"
    rendered = render_prompt(prompts, "panel.review_intent", review_intent=sentinel)
    if sentinel not in rendered:
        return f"{rendered}\n\n{text}"
    return rendered.replace(sentinel, text)


def compose_brief_with_review_intent(
    prompts: dict[str, str],
    *,
    brief: str,
    review_intent: str,
) -> str:
    document = (brief or "").strip()
    intent = render_review_intent_message(prompts, review_intent)
    if not intent:
        return document
    if not document:
        return intent
    return f"{intent}\n\n{document}"


def session_brief_for_llm(config: PanelSessionConfig, prompts: dict[str, str]) -> str:
    return compose_brief_with_review_intent(
        prompts,
        brief=config.brief,
        review_intent=config.review_intent,
    )
