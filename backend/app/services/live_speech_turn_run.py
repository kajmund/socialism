"""Execute one live-speech expert turn: LLM stream, tools, and TTS."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

from elevenlabs.core.api_error import ApiError as ElevenLabsApiError
from openai import OpenAIError

from app.config import settings
from app.services import jobs as jobs_service
from app.services.conversation_controller import ConversationEvent
from app.services.expert_turn_cancel import bind_turn_cancel
from app.services.live_speech_admit import admit_voice_turn, current_workspace_state
from app.services.live_speech_progress import bind_tool_progress
from app.services.persona_chat import ChatTurnError
from app.services.sme_expert_turns import execute_expert_turn
from app.services.speculative_results import speculative_results
from app.services.speech_segmenter import SpeechSegmenter, VisibleSpeechText, strip_voice_tags
from app.services.turn_amendment import bound_amendment_channel

if TYPE_CHECKING:
    from app.services.live_speech_runtime import LiveSpeechRuntime

_V4_TURBO_MODEL = "eleven_v4_turbo"
_V4_DELIVERY_PROMPT_KEY = "chat.expert.live_speech_delivery"


async def run_voice_turn(runtime: LiveSpeechRuntime, turn_id: str, text: str) -> None:
    await runtime._state("thinking")
    runtime._request_id = request_id = f"voice-{uuid4().hex}"
    runtime._user_text, runtime._assistant_text = text, ""
    factory = jobs_service.job_session_factory()
    workspace_state = await current_workspace_state(factory, runtime.scope)
    turn = await admit_voice_turn(factory, runtime.scope, request_id, text)
    runtime._request_fence = turn.fence
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    runtime._coordinator.reset_turn()
    tts_task = asyncio.create_task(_speak(runtime, turn_id, queue))
    runtime._cues.start_waiting(turn_id)
    on_token = _main_token_handler(runtime, turn_id, queue)
    try:
        with (
            bind_tool_progress(runtime._cues.on_tool_progress),
            bind_turn_cancel(runtime._turn_cancel),
            speculative_results(runtime._speculation.matches(text)),
            bound_amendment_channel(runtime),
        ):
            done = await execute_expert_turn(
                factory,
                request_id=request_id,
                persona_id=runtime.scope.expert_id,
                message=text,
                image_sha256=None,
                fence=turn.fence,
                token=turn.lease_token,
                on_token=on_token,
                workspace_id=runtime.scope.workspace_id,
                workspace_state=workspace_state,
                on_client_tools=runtime._client_tools(turn_id),
                extra_system_prompt_key=(
                    _V4_DELIVERY_PROMPT_KEY
                    if settings.live_speech_tts_model == _V4_TURBO_MODEL
                    else None
                ),
                assistant_reply_transform=(
                    strip_voice_tags
                    if settings.live_speech_tts_model == _V4_TURBO_MODEL
                    else None
                ),
            )
        queue.put_nowait(None)
        await _finish_spoken_turn(runtime, turn_id, done.reply, tts_task)
    except asyncio.CancelledError:
        await runtime._stop_turn_helpers(tts_task)
        raise
    except (ChatTurnError, ElevenLabsApiError, OpenAIError, RuntimeError, TimeoutError):
        await runtime._stop_turn_helpers(tts_task)
        await runtime._error("chat_turn_failed", "Expert turn failed", True)


def _main_token_handler(
    runtime: LiveSpeechRuntime,
    turn_id: str,
    queue: asyncio.Queue[str | None],
) -> Callable[[str], Awaitable[None]]:
    visible_text = VisibleSpeechText()

    async def on_token(delta: str) -> None:
        if turn_id != runtime._turn_id:
            return
        if not runtime._first_delta_logged and runtime._final_at is not None:
            runtime._first_delta_logged = True
            runtime._coordinator.note_main_text()
            runtime._metrics.add(
                "server.first_llm_delta", (monotonic() - runtime._final_at) * 1000,
            )
        display_delta = visible_text.push(delta)
        runtime._assistant_text += display_delta
        if display_delta:
            await runtime._emit_json(
                {
                    "type": "assistant.text.delta",
                    "turn_id": turn_id,
                    "sequence": runtime._next_sequence(),
                    "text": display_delta,
                }
            )
        queue.put_nowait(delta)

    return on_token


async def _finish_spoken_turn(
    runtime: LiveSpeechRuntime,
    turn_id: str,
    reply: str,
    tts_task: asyncio.Task[None],
) -> None:
    try:
        await tts_task
        runtime._coordinator.allow_progress()
    except (ElevenLabsApiError, TimeoutError):
        await _emit_final_text(runtime, turn_id, reply)
        await runtime._error("tts_failed", "Speech synthesis failed", True)
        await runtime._state("listening")
        return
    await _emit_final_text(runtime, turn_id, reply)
    runtime._cues.cancel_waiting()
    if runtime._final_at is not None:
        runtime._metrics.add("server.turn_complete", (monotonic() - runtime._final_at) * 1000)
    runtime._conversation.handle(ConversationEvent(kind="ai_idle", turn_id=turn_id))
    await runtime._state("listening")


async def _emit_final_text(runtime: LiveSpeechRuntime, turn_id: str, reply: str) -> None:
    await runtime._emit_json(
        {
            "type": "assistant.text.final",
            "turn_id": turn_id,
            "text": reply,
            "interrupted": False,
        }
    )


async def _speak(
    runtime: LiveSpeechRuntime,
    turn_id: str,
    queue: asyncio.Queue[str | None],
) -> None:
    segmenter = SpeechSegmenter()
    while True:
        delta = await queue.get()
        segments = segmenter.finish() if delta is None else segmenter.push(delta)
        for segment in segments:
            if turn_id != runtime._turn_id:
                return
            await runtime._coordinator.play_main(segment, turn_id)
            runtime._spoken_text = runtime._coordinator.spoken_text
        if delta is None:
            return
