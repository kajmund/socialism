"""Amend an in-flight live-speech turn without restarting it (Fas 2)."""

from __future__ import annotations


async def amend_turn(runtime, turn_id: str | None, text: str) -> None:
    """Stop speaking and fold an amendment into the running turn.

    The in-flight tool episode drains the amendment between rounds and revises
    its reply instead of restarting the whole turn.
    """
    task = runtime._turn_task
    if task is None or task.done() or turn_id != runtime._turn_id:
        return
    runtime._conversation.ai_interrupted()
    runtime._coordinator.interrupt_playback()
    await runtime._emit_json(
        {"type": "assistant.amended", "turn_id": turn_id, "text": text}
    )
    if runtime._amendment_queue is not None:
        await runtime._amendment_queue.put(text)
