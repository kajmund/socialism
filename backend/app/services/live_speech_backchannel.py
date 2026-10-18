"""When to interrupt a spoken reply. One expert and a group both use this."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Literal

from app.config import settings
from app.services.live_speech_phrases import classify_backchannel_llm

logger = logging.getLogger(__name__)

BackchannelKind = Literal["backchannel", "interruption", "new_question", "uncertain"]
BargeAction = Literal["ignore", "barge", "wait"]

_PUNCT = re.compile(r"[^\w\s?åäöÅÄÖ-]+", re.UNICODE)
_SPACES = re.compile(r"\s+")
URGENT = frozenset({"stopp", "nej", "vänta", "stop", "wait", "no"})
BACKCHANNELS = frozenset(
    {
        "mm",
        "mhm",
        "mm hm",
        "mmhm",
        "just det",
        "jajust",
        "ja precis",
        "okej",
        "ok",
        "ja",
        "jaha",
        "aha",
        "hm",
        "hmm",
    }
)
_QUESTION_STARTS = ("vad", "hur", "varför", "varfor", "vilken", "vilket", "kan du", "skulle")
_INTERRUPT_STARTS = ("ja men", "ja men ", "nej men", "okej men", "ok men")


def normalize_utterance(text: str) -> str:
    folded = _PUNCT.sub(" ", text.casefold())
    return _SPACES.sub(" ", folded).strip()


def classify_utterance(
    text: str,
    *,
    duration_ms: float | None = None,
    echoed: str | None = None,
) -> BackchannelKind:
    normalized = normalize_utterance(text)
    if not normalized:
        kind: BackchannelKind = "uncertain"
    elif echoed and normalize_utterance(echoed) == normalized:
        kind = "backchannel"
    elif _urgent(normalized) or _interrupts(normalized):
        kind = "interruption"
    elif "?" in text or normalized.startswith(_QUESTION_STARTS):
        kind = "new_question"
    elif _backchannel_only(normalized) and (
        duration_ms is None or duration_ms <= settings.live_speech_backchannel_max_ms
    ):
        kind = "backchannel"
    else:
        kind = "uncertain"
    return kind


def utterance_barge(
    text: str,
    *,
    final: bool,
    duration_ms: float | None = None,
    echoed: str | None = None,
) -> tuple[BargeAction, BackchannelKind]:
    """One interruption rule for a single expert and a group.

    A short mm is ignored. A clear interruption stops the reply at once.
    Anything else waits until the utterance is finished or the confirm beat ends.
    """
    kind = classify_utterance(text, duration_ms=duration_ms, echoed=echoed)
    if kind == "backchannel":
        action: BargeAction = "ignore"
    elif final or kind in {"interruption", "new_question"}:
        action = "barge"
    else:
        action = "wait"
    return action, kind


async def confirm_barge(prompt: str, text: str) -> bool:
    """Wait the confirm beat, then say whether the reply should stop."""
    started = monotonic()
    llm = asyncio.create_task(classify_backchannel_llm(prompt, text))
    try:
        await asyncio.sleep(settings.live_speech_backchannel_confirm_ms / 1000)
        kind = llm.result() if llm.done() else "uncertain"
    finally:
        if not llm.done():
            llm.cancel()
    logger.info(
        "live_speech.backchannel_classified kind=%s latency_ms=%.1f",
        kind,
        (monotonic() - started) * 1000,
    )
    return kind != "backchannel"


class SpeechBarge:
    """Decides and waits. The caller only says what stopping this session means."""

    def __init__(
        self,
        stop: Callable[[str], Awaitable[None]],
        *,
        on_backchannel: Callable[[str], Awaitable[None]] | None = None,
        prompt: Callable[[], str] | None = None,
    ) -> None:
        self._stop = stop
        self._on_backchannel = on_backchannel
        self._prompt = prompt or (lambda: "")
        self.task: asyncio.Task[None] | None = None

    async def consider(
        self,
        text: str,
        *,
        final: bool,
        duration_ms: float | None = None,
        echoed: str | None = None,
    ) -> bool:
        """True when the utterance must not start a new turn."""
        action, kind = utterance_barge(
            text,
            final=final,
            duration_ms=duration_ms,
            echoed=echoed,
        )
        if action == "wait":
            self._schedule(text)
            return True
        self.cancel()
        if action == "ignore":
            await self._note_backchannel(text)
            return True
        await self._stop(kind)
        return False

    def cancel(self) -> None:
        task = self.task
        if task is None or task is asyncio.current_task():
            if task is asyncio.current_task():
                self.task = None
            return
        self.task = None
        if not task.done():
            task.cancel()

    async def aclose(self) -> None:
        task = self.task
        self.cancel()
        if task is not None and not task.done():
            await asyncio.gather(task, return_exceptions=True)

    def _schedule(self, text: str) -> None:
        if self.task is not None and not self.task.done():
            return
        self.task = asyncio.create_task(self._resolve(text))

    async def _resolve(self, text: str) -> None:
        try:
            stop = await confirm_barge(self._prompt(), text)
        except asyncio.CancelledError:
            return
        if not stop:
            await self._note_backchannel(text)
            return
        await self._stop("uncertain")

    async def _note_backchannel(self, text: str) -> None:
        if self._on_backchannel is not None:
            await self._on_backchannel(text)


def _interrupts(normalized: str) -> bool:
    return any(normalized.startswith(prefix) for prefix in _INTERRUPT_STARTS) or (
        " men " in f" {normalized} " and not _backchannel_only(normalized)
    )


def _urgent(normalized: str) -> bool:
    tokens = set(normalized.split())
    return bool(tokens & URGENT) or normalized in URGENT


def _backchannel_only(normalized: str) -> bool:
    if normalized in BACKCHANNELS:
        return True
    tokens = normalized.split()
    return bool(tokens) and all(token in BACKCHANNELS or token in {"mm", "okej", "ok"} for token in tokens)
