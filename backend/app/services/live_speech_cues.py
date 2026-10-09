"""Listener cues, backchannel handling and progress talk for one voice session."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import TYPE_CHECKING

from app.config import settings
from app.services.live_speech_backchannel import classify_utterance
from app.services.live_speech_phrases import (
    BACKCHANNEL_PROMPT_KEY,
    LISTENER_PROMPT_KEY,
    OPENING_PROMPT_KEY,
    PROGRESS_PROMPT_KEY,
    ProgressContext,
    classify_backchannel_llm,
    generate_listener_phrase,
    generate_opening_phrase,
    generate_progress_phrase,
)
from app.services.live_speech_progress import ToolProgress

if TYPE_CHECKING:
    from app.services.live_speech_runtime import LiveSpeechRuntime

logger = logging.getLogger(__name__)


class LiveSpeechCues:
    def __init__(self, runtime: LiveSpeechRuntime) -> None:
        self._rt = runtime
        self.listener_task: asyncio.Task[None] | None = None
        self.uncertain_task: asyncio.Task[None] | None = None
        self.waiting_task: asyncio.Task[None] | None = None
        self.opening_task: asyncio.Task[None] | None = None
        self.progress_tasks: set[asyncio.Task[None]] = set()

    def cancel_all(self) -> list[asyncio.Task[None]]:
        tasks = [
            task
            for task in (
                self.listener_task,
                self.uncertain_task,
                self.waiting_task,
                self.opening_task,
            )
            if task is not None
        ]
        tasks.extend(self.progress_tasks)
        for task in tasks:
            task.cancel()
        self.listener_task = None
        self.uncertain_task = None
        self.waiting_task = None
        self.opening_task = None
        return tasks

    def assistant_active(self) -> bool:
        turn = self._rt._turn_task
        opening = self.opening_task
        return (turn is not None and not turn.done()) or (
            opening is not None and not opening.done()
        )

    def restart_listener(self) -> None:
        self.stop_listener()
        if self.assistant_active() or self._rt._muted:
            return
        self.listener_task = asyncio.create_task(self._listener_loop())

    def stop_listener(self) -> None:
        if self.listener_task is not None:
            self.listener_task.cancel()
            self.listener_task = None

    def cancel_uncertain(self) -> None:
        if self.uncertain_task is not None:
            self.uncertain_task.cancel()
            self.uncertain_task = None

    def cancel_waiting(self) -> None:
        if self.waiting_task is not None:
            self.waiting_task.cancel()

    def start_waiting(self, turn_id: str) -> None:
        self.waiting_task = asyncio.create_task(self._maybe_waiting(turn_id))

    def start_opening(self) -> None:
        if self._rt._muted or self.opening_task is not None:
            return
        self.opening_task = asyncio.create_task(self._speak_opening())

    async def _speak_opening(self) -> None:
        started = monotonic()
        try:
            phrase = await generate_opening_phrase(
                self._rt.scope.prompts.get(OPENING_PROMPT_KEY, ""),
                self._rt.scope.recent_turns,
            )
            if not phrase or self._rt._closed or self._rt._muted:
                return
            logger.info(
                "live_speech.opening_phrase latency_ms=%.1f",
                (monotonic() - started) * 1000,
            )
            await self._rt._state("speaking")
            await self._rt._emit_json(
                {
                    "type": "assistant.opening",
                    "turn_id": "opening",
                    "text": phrase,
                }
            )
            await self._rt._coordinator.play_aside(phrase, "opening")
            if not self._rt._closed and self._rt._turn_task is None:
                await self._rt._state("listening")
        except asyncio.CancelledError:
            return

    async def on_partial(self, item_id: str, delta: str) -> None:
        runtime = self._rt
        if not runtime._first_partial_logged and runtime._speech_started_at is not None:
            runtime._first_partial_logged = True
            logger.info(
                "live_speech.first_partial latency_ms=%.1f",
                (monotonic() - runtime._speech_started_at) * 1000,
            )
        text = runtime._partials.get(item_id, "") + delta
        runtime._partials[item_id] = text
        runtime._user_text_partial = text
        revision = runtime._revisions.get(item_id, 0) + 1
        runtime._revisions[item_id] = revision
        if self.echoes_listener(text):
            return
        await runtime._emit_json(
            {
                "type": "transcript.partial",
                "item_id": item_id,
                "revision": revision,
                "text": text,
            }
        )
        if self.assistant_active():
            await self.classify_user_speech(text, final=False)

    async def classify_user_speech(self, text: str, *, final: bool) -> bool:
        runtime = self._rt
        duration = None
        if runtime._speech_started_at is not None:
            duration = (monotonic() - runtime._speech_started_at) * 1000
        last_aside = runtime._coordinator.spoken_asides[-1] if runtime._coordinator.spoken_asides else None
        kind = classify_utterance(text, duration_ms=duration, echoed=last_aside)
        if kind != "uncertain":
            self.cancel_uncertain()
        if kind == "backchannel":
            await self._emit_backchannel(text, kind)
            return True
        if kind in {"interruption", "new_question"}:
            await self.barge_in(kind)
            return False
        if final:
            await self.barge_in("uncertain")
            return False
        self._schedule_uncertain(text)
        return True

    def echoes_listener(self, text: str) -> bool:
        last = (
            self._rt._coordinator.spoken_asides[-1]
            if self._rt._coordinator.spoken_asides
            else ""
        )
        return bool(last) and text.casefold().strip() == last.casefold()

    async def barge_in(self, reason: str) -> None:
        started = monotonic()
        self._rt._coordinator.drop_aside()
        if self.assistant_active():
            await self._rt.cancel_turn(self._rt._turn_id, reason)
            logger.info(
                "live_speech.barge_in reason=%s latency_ms=%.1f",
                reason,
                (monotonic() - started) * 1000,
            )

    async def on_tool_progress(self, event: ToolProgress) -> None:
        delay = (
            settings.live_speech_tool_progress_ms / 1000
            if event.kind == "started"
            else 0.0
        )
        task = asyncio.create_task(self._delayed_progress(event, delay))
        self.progress_tasks.add(task)
        task.add_done_callback(self.progress_tasks.discard)

    def _schedule_uncertain(self, text: str) -> None:
        if self.uncertain_task is not None and not self.uncertain_task.done():
            return
        self.uncertain_task = asyncio.create_task(self._resolve_uncertain(text))

    async def _resolve_uncertain(self, text: str) -> None:
        started = monotonic()
        prompt = self._rt.scope.prompts.get(BACKCHANNEL_PROMPT_KEY, "")
        llm = asyncio.create_task(classify_backchannel_llm(prompt, text))
        try:
            await asyncio.sleep(settings.live_speech_backchannel_confirm_ms / 1000)
            kind = llm.result() if llm.done() else "uncertain"
            if kind == "backchannel":
                await self._emit_backchannel(text, kind)
                return
            await self.barge_in("uncertain")
            logger.info(
                "live_speech.backchannel_classified kind=%s latency_ms=%.1f",
                kind,
                (monotonic() - started) * 1000,
            )
        finally:
            if not llm.done():
                llm.cancel()

    async def _emit_backchannel(self, text: str, classification: str) -> None:
        await self._rt._emit_json(
            {
                "type": "transcript.backchannel",
                "turn_id": self._rt._turn_id,
                "text": text,
                "classification": classification,
            }
        )

    async def _listener_loop(self) -> None:
        try:
            await asyncio.sleep(settings.live_speech_listener_after_ms / 1000)
            while not self._rt._closed:
                if self._skip_listener():
                    return
                phrase = await generate_listener_phrase(
                    self._rt.scope.prompts.get(LISTENER_PROMPT_KEY, ""),
                    partial=self._rt._user_text_partial,
                    spoken=" ".join(self._rt._coordinator.spoken_asides),
                )
                if phrase and not self._skip_listener():
                    logger.info("live_speech.listener_phrase")
                    await self._rt._coordinator.play_aside(phrase, "listener")
                await asyncio.sleep(settings.live_speech_listener_cooldown_ms / 1000)
        except asyncio.CancelledError:
            return

    def _skip_listener(self) -> bool:
        return (
            self._rt._closed
            or self._rt._muted
            or self.assistant_active()
            or self._rt._commit_at is not None
        )

    async def _maybe_waiting(self, turn_id: str) -> None:
        try:
            await asyncio.sleep(settings.live_speech_waiting_suppress_ms / 1000)
            if self._rt._coordinator.main_text_seen or self._rt._closed:
                return
            await self._speak_progress(
                turn_id,
                ProgressContext(kind="waiting", user_text=self._rt._user_text),
            )
        except asyncio.CancelledError:
            return

    async def _delayed_progress(self, event: ToolProgress, delay: float) -> None:
        try:
            if delay:
                await asyncio.sleep(delay)
            if self._rt._closed:
                return
            await self._speak_progress(
                self._rt._turn_id or "progress",
                ProgressContext(
                    kind=event.kind,
                    tool_name=event.tool_name,
                    remaining=event.remaining,
                    summary=event.summary,
                    spoken=" ".join(self._rt._coordinator.spoken_asides),
                    user_text=self._rt._user_text,
                ),
            )
        except asyncio.CancelledError:
            return

    async def _speak_progress(self, turn_id: str, context: ProgressContext) -> None:
        started = monotonic()
        phrase = await generate_progress_phrase(
            self._rt.scope.prompts.get(PROGRESS_PROMPT_KEY, ""),
            context,
        )
        if not phrase or self._rt._closed:
            return
        logger.info(
            "live_speech.waiting_phrase kind=%s latency_ms=%.1f",
            context.kind,
            (monotonic() - started) * 1000,
        )
        await self._rt._emit_json(
            {
                "type": "assistant.waiting",
                "turn_id": turn_id,
                "phrase_id": context.kind,
                "text": phrase,
            }
        )
        await self._rt._coordinator.play_aside(phrase, turn_id)
