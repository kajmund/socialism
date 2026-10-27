"""Context-aware STT correction for committed live-speech utterances.

The streaming pass and the offline second pass transcribe acoustics. This pass
shows the recent conversation and the committed text to the configured Cerebras
chat model, which repairs occasional misheard words. It is an enhancement, not
a fallback: on timeout, provider error, or an unchanged verdict the caller
keeps the uncorrected text.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel

from app.llm import complete_structured
from app.services.expert_reasoning import bound_expert_profile
from app.services.live_speech_phrases import _PHRASE_ERRORS

logger = logging.getLogger(__name__)

CORRECTION_PROMPT_KEY = "chat.expert.live_speech_correction"

_MAX_TURNS = 6


class SttCorrectionDecision(BaseModel):
    corrected_text: str
    changed: bool


def conversation_block(turns: Sequence[tuple[str, str]]) -> str:
    lines = [
        f"{'User' if role == 'user' else 'Expert'}: {text}"
        for role, text in list(turns)[-_MAX_TURNS:]
    ]
    return "\n".join(lines)


async def correct_transcript(
    prompt: str,
    conversation: Sequence[tuple[str, str]],
    text: str,
    *,
    timeout: float,
) -> SttCorrectionDecision | None:
    if not prompt.strip() or not text.strip():
        return None
    block = conversation_block(conversation) or "(inget tidigare samtal)"
    try:
        with bound_expert_profile("fast"):
            return await complete_structured(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"{block}\n\n{text}",
                    },
                ],
                SttCorrectionDecision,
                prompt_key=CORRECTION_PROMPT_KEY,
                max_tokens=120,
                timeout=timeout,
            )
    except _PHRASE_ERRORS:
        logger.info("live_speech.correction_failed")
        return None
