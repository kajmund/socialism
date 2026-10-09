"""Resolve a concrete LLM configuration from prompt assignment + Auto needs."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.config import settings
from app.llm.chat_model import remember_chat_model
from app.llm.jev import JevError, JevNeedClassifier, JevNeedDecision
from app.llm.runtime_override import (
    CachedLlmConfiguration,
    LLMCallKind,
    LlmResolution,
    PromptLlmAssignmentView,
    SelectionRole,
    assignment_for_prompt,
    bound_llm_resolution,
    bound_llm_runtime,
    cached_configurations,
    default_configuration,
    settings_runtime_view,
)
from app.services.expert_reasoning import (
    EXPERT_PROMPT_KEYS,
    current_expert_profile,
)

logger = logging.getLogger(__name__)

AUTO_REASON_SELECTED = "auto_selected"
AUTO_REASON_LOW_CONFIDENCE = "auto_low_confidence"
AUTO_REASON_NO_MATCH = "auto_no_match"
AUTO_REASON_INVALID = "auto_invalid_need"
AUTO_REASON_ERROR = "auto_error"
AUTO_REASON_UNAVAILABLE = "auto_unavailable"


@dataclass(frozen=True)
class LlmCallRequirements:
    needs_vision: bool | None = None
    needs_tools: bool | None = None
    needs_structured_output: bool | None = None
    needs_long_context: bool | None = None
    allowed_configuration_ids: tuple[int, ...] | None = None


@dataclass(frozen=True)
class TaskNeed:
    speed_class: SelectionRole
    needs_vision: bool
    needs_tools: bool
    needs_structured_output: bool
    needs_long_context: bool
    confidence: float


class LlmNeedClassifier(Protocol):
    async def classify(
        self,
        *,
        prompt_key: str,
        messages: list[dict[str, Any]],
        call_kind: LLMCallKind,
        state: dict[str, Any],
    ) -> JevNeedDecision: ...


class UnavailableNeedClassifier:
    async def classify(
        self,
        *,
        prompt_key: str,
        messages: list[dict[str, Any]],
        call_kind: LLMCallKind,
        state: dict[str, Any],
    ) -> JevNeedDecision:
        del prompt_key, messages, call_kind, state
        raise JevError("TYPESAFE_API_KEY is not configured")


_need_classifier: LlmNeedClassifier | None = None


def set_need_classifier(classifier: LlmNeedClassifier | None) -> None:
    global _need_classifier
    _need_classifier = classifier


def current_need_classifier() -> LlmNeedClassifier:
    if _need_classifier is not None:
        return _need_classifier
    if settings.typesafe_api_key.strip():
        return JevNeedClassifier()
    return UnavailableNeedClassifier()


def messages_have_images(messages: Sequence[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                kind = str(part.get("type") or "")
                if kind in {"image_url", "image", "input_image"}:
                    return True
                if part.get("image_url") is not None:
                    return True
    return False


def _truncate_messages(
    messages: Sequence[dict[str, Any]], budget: int
) -> list[dict[str, Any]]:
    clipped: list[dict[str, Any]] = []
    used = 0
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            texts: list[str] = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif isinstance(part, dict) and part.get("type") in {
                    "image_url",
                    "image",
                    "input_image",
                }:
                    texts.append("[image]")
            text = "\n".join(texts)
        else:
            text = ""
        remaining = budget - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining]
        clipped.append({"role": role, "content": text})
        used += len(text)
    return clipped


def _hard_need_flags(
    *,
    messages: Sequence[dict[str, Any]],
    call_kind: LLMCallKind,
    requirements: LlmCallRequirements | None,
) -> tuple[bool, bool, bool, bool]:
    vision = messages_have_images(messages)
    tools = call_kind == "tools"
    structured = call_kind == "structured"
    long_context = False
    if requirements is not None:
        vision = vision or bool(requirements.needs_vision)
        tools = tools or bool(requirements.needs_tools)
        structured = structured or bool(requirements.needs_structured_output)
        long_context = bool(requirements.needs_long_context)
    return vision, tools, structured, long_context


def _meets_capabilities(row: CachedLlmConfiguration, need: TaskNeed) -> bool:
    if need.needs_vision and not row.capability_vision:
        return False
    if need.needs_tools and not row.capability_tools:
        return False
    if need.needs_structured_output and not row.capability_structured_output:
        return False
    if need.needs_long_context and not row.capability_long_context:
        return False
    return True


def match_auto_configuration(
    need: TaskNeed,
    candidates: Sequence[CachedLlmConfiguration],
    *,
    allowed_configuration_ids: tuple[int, ...] | None = None,
) -> CachedLlmConfiguration | None:
    allowed = set(allowed_configuration_ids) if allowed_configuration_ids else None
    capable = [
        row
        for row in candidates
        if row.enabled_for_auto
        and (allowed is None or row.id in allowed)
        and _meets_capabilities(row, need)
    ]
    role_match = [row for row in capable if row.selection_role == need.speed_class]
    if not role_match:
        return None
    return sorted(role_match, key=lambda row: (row.priority, row.id))[0]


def _fallback_configuration(
    assignment: PromptLlmAssignmentView,
) -> CachedLlmConfiguration | None:
    if assignment.configuration_id is not None:
        row = cached_configurations().get(assignment.configuration_id)
        if row is not None:
            return row
    return default_configuration()


def _resolution_from_config(  # noqa: PLR0913
    row: CachedLlmConfiguration | None,
    *,
    prompt_key: str | None,
    selection_mode: Literal["default", "fixed", "auto"],
    reason_code: str,
    fallback: bool,
    call_kind: LLMCallKind,
    auto_confidence: float | None = None,
    speed_class: SelectionRole | None = None,
) -> LlmResolution:
    if row is None:
        view = settings_runtime_view()
        selected_id = None
    else:
        view = row.view
        selected_id = row.id
    return LlmResolution(
        view=view,
        prompt_key=prompt_key,
        selection_mode=selection_mode,
        selected_configuration_id=selected_id,
        auto_confidence=auto_confidence,
        reason_code=reason_code,
        fallback=fallback,
        call_kind=call_kind,
        speed_class=speed_class,
    )


def _log_resolution(resolution: LlmResolution) -> None:
    logger.info(
        "llm.runtime.resolved prompt_key=%s mode=%s config_id=%s "
        "reason=%s fallback=%s confidence=%s kind=%s",
        resolution.prompt_key,
        resolution.selection_mode,
        resolution.selected_configuration_id,
        resolution.reason_code,
        resolution.fallback,
        resolution.auto_confidence,
        resolution.call_kind,
    )


def _expert_profile_resolution(
    *,
    prompt_key: str | None,
    messages: Sequence[dict[str, Any]],
    call_kind: LLMCallKind,
    assignment: PromptLlmAssignmentView,
    requirements: LlmCallRequirements | None,
) -> LlmResolution | None:
    routed_profile = (
        current_expert_profile()
        if settings.expert_reasoning_route_enabled and prompt_key in EXPERT_PROMPT_KEYS
        else None
    )
    if routed_profile is None:
        return None
    vision, tools, structured, long_context = _hard_need_flags(
        messages=messages,
        call_kind=call_kind,
        requirements=requirements,
    )
    allowed = assignment.allowed_configuration_ids
    if requirements is not None and requirements.allowed_configuration_ids is not None:
        allowed = requirements.allowed_configuration_ids
    matched = match_auto_configuration(
        TaskNeed(
            speed_class=routed_profile,
            needs_vision=vision,
            needs_tools=tools,
            needs_structured_output=structured,
            needs_long_context=long_context,
            confidence=1.0,
        ),
        list(cached_configurations().values()),
        allowed_configuration_ids=allowed,
    )
    if matched is None:
        logger.info(
            "llm.runtime.expert_reasoning_no_match prompt_key=%s profile=%s",
            prompt_key,
            routed_profile,
        )
        return None
    return _resolution_from_config(
        matched,
        prompt_key=prompt_key,
        selection_mode="auto",
        reason_code="expert_reasoning_selected",
        fallback=False,
        call_kind=call_kind,
        auto_confidence=1.0,
        speed_class=routed_profile,
    )


def _static_assignment_resolution(
    assignment: PromptLlmAssignmentView,
    *,
    prompt_key: str | None,
    call_kind: LLMCallKind,
) -> LlmResolution | None:
    if assignment.mode == "default":
        return _resolution_from_config(
            default_configuration(),
            prompt_key=prompt_key,
            selection_mode="default",
            reason_code="default",
            fallback=False,
            call_kind=call_kind,
        )
    if assignment.mode != "fixed":
        return None
    row = (
        cached_configurations().get(assignment.configuration_id)
        if assignment.configuration_id is not None
        else None
    )
    return _resolution_from_config(
        row or default_configuration(),
        prompt_key=prompt_key,
        selection_mode="fixed",
        reason_code="fixed",
        fallback=False,
        call_kind=call_kind,
    )


async def resolve_llm_runtime(  # noqa: PLR0911
    *,
    prompt_key: str | None,
    messages: Sequence[dict[str, Any]],
    call_kind: LLMCallKind,
    requirements: LlmCallRequirements | None = None,
) -> LlmResolution:
    assignment = assignment_for_prompt(prompt_key)
    routed = _expert_profile_resolution(
        prompt_key=prompt_key,
        messages=messages,
        call_kind=call_kind,
        assignment=assignment,
        requirements=requirements,
    )
    if routed is not None:
        _log_resolution(routed)
        return routed
    static = _static_assignment_resolution(
        assignment, prompt_key=prompt_key, call_kind=call_kind
    )
    if static is not None:
        _log_resolution(static)
        return static

    fallback = _fallback_configuration(assignment)
    hard_vision, hard_tools, hard_structured, hard_long = _hard_need_flags(
        messages=messages,
        call_kind=call_kind,
        requirements=requirements,
    )
    allowed = assignment.allowed_configuration_ids
    if requirements is not None and requirements.allowed_configuration_ids is not None:
        allowed = requirements.allowed_configuration_ids
    try:
        decision = await current_need_classifier().classify(
            prompt_key=prompt_key or "",
            messages=list(messages),
            call_kind=call_kind,
            state={
                "prompt_key": prompt_key,
                "call_kind": call_kind,
                "hard_requirements": {
                    "vision": hard_vision,
                    "tools": hard_tools,
                    "structured_output": hard_structured,
                    "long_context": hard_long,
                },
                "messages": _truncate_messages(
                    messages, settings.jev_state_char_budget
                ),
            },
        )
    except JevError as exc:
        message = str(exc)
        if "TYPESAFE_API_KEY" in message:
            reason = AUTO_REASON_UNAVAILABLE
        elif "invalid" in message or "missing" in message:
            reason = AUTO_REASON_INVALID
        else:
            reason = AUTO_REASON_ERROR
        logger.info("llm.runtime.auto_fallback reason=%s error=%s", reason, exc)
        resolution = _resolution_from_config(
            fallback,
            prompt_key=prompt_key,
            selection_mode="auto",
            reason_code=reason,
            fallback=True,
            call_kind=call_kind,
        )
        _log_resolution(resolution)
        return resolution
    except Exception as exc:  # noqa: BLE001
        logger.info("llm.runtime.auto_fallback reason=%s error=%s", AUTO_REASON_ERROR, exc)
        resolution = _resolution_from_config(
            fallback,
            prompt_key=prompt_key,
            selection_mode="auto",
            reason_code=AUTO_REASON_ERROR,
            fallback=True,
            call_kind=call_kind,
        )
        _log_resolution(resolution)
        return resolution

    if decision.confidence < settings.jev_confidence_threshold:
        resolution = _resolution_from_config(
            fallback,
            prompt_key=prompt_key,
            selection_mode="auto",
            reason_code=AUTO_REASON_LOW_CONFIDENCE,
            fallback=True,
            call_kind=call_kind,
            auto_confidence=decision.confidence,
            speed_class=decision.speed_class,
        )
        _log_resolution(resolution)
        return resolution

    need = TaskNeed(
        speed_class=decision.speed_class,
        needs_vision=hard_vision or decision.needs_vision,
        needs_tools=hard_tools or decision.needs_tools,
        needs_structured_output=hard_structured or decision.needs_structured_output,
        needs_long_context=hard_long or decision.needs_long_context,
        confidence=decision.confidence,
    )
    matched = match_auto_configuration(
        need,
        list(cached_configurations().values()),
        allowed_configuration_ids=allowed,
    )
    if matched is None:
        resolution = _resolution_from_config(
            fallback,
            prompt_key=prompt_key,
            selection_mode="auto",
            reason_code=AUTO_REASON_NO_MATCH,
            fallback=True,
            call_kind=call_kind,
            auto_confidence=decision.confidence,
            speed_class=decision.speed_class,
        )
        _log_resolution(resolution)
        return resolution
    resolution = _resolution_from_config(
        matched,
        prompt_key=prompt_key,
        selection_mode="auto",
        reason_code=AUTO_REASON_SELECTED,
        fallback=False,
        call_kind=call_kind,
        auto_confidence=decision.confidence,
        speed_class=decision.speed_class,
    )
    _log_resolution(resolution)
    return resolution


@asynccontextmanager
async def llm_call_runtime(
    prompt_key: str | None,
    messages: Sequence[dict[str, Any]],
    call_kind: LLMCallKind,
    requirements: LlmCallRequirements | None = None,
):
    if not prompt_key:
        yield None
        return
    resolution = await resolve_llm_runtime(
        prompt_key=prompt_key,
        messages=messages,
        call_kind=call_kind,
        requirements=requirements,
    )
    with bound_llm_runtime(resolution.view), bound_llm_resolution(resolution):
        try:
            yield resolution
        finally:
            remember_chat_model(resolution)
