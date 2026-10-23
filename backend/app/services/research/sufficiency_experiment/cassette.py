"""Jev cassette for paired arm runs. Experiment-only; never production.

Each response is keyed by the question set, the canonical state and the model.
Replay is strictly ordered: a missing or out-of-order entry raises instead of
falling back to a live call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from app.jev.system import JevSystemOne, JevSystemOneResult, JevUsage


class CassetteError(RuntimeError):
    """A cassette cannot serve the requested call."""


class CassetteMissError(CassetteError):
    """The cassette has no matching entry."""


class CassetteOrderError(CassetteError):
    """The cassette was recorded for a different call order."""


def entry_key(*, questions: object, state: object, model: str) -> str:
    payload = {"questions": questions, "state": state, "model": model}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class RecordingJev:
    def __init__(self, inner: JevSystemOne) -> None:
        self._inner = inner
        self.entries: list[dict[str, object]] = []

    async def ask(self, *, state, questions, model: str, timeout_seconds: float):
        result = await self._inner.ask(
            state=state,
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        self.entries.append(
            {
                "key": entry_key(questions=questions, state=state, model=model),
                "model": result.model,
                "answers": result.answers,
                "latency_ms": result.latency_ms,
                "input_chars": result.input_chars,
                "usage": {
                    "prompt_tokens": result.usage.prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                    "total_tokens": result.usage.total_tokens,
                },
            }
        )
        return result

    def save(self, path: Path, *, metadata: Mapping[str, object] | None = None) -> None:
        payload = {
            "version": 1,
            "metadata": dict(metadata or {}),
            "entries": self.entries,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class CassetteJev:
    def __init__(self, entries: list[dict[str, object]]) -> None:
        self._entries = list(entries)
        self._cursor = 0

    @classmethod
    def load(cls, path: Path) -> CassetteJev:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(list(payload["entries"]))

    async def ask(self, *, state, questions, model: str, timeout_seconds: float):
        if self._cursor >= len(self._entries):
            raise CassetteMissError("cassette exhausted")
        expected = self._entries[self._cursor]
        key = entry_key(questions=questions, state=state, model=model)
        if expected["key"] != key:
            raise CassetteOrderError(
                f"cassette entry {self._cursor} does not match the requested call"
            )
        self._cursor += 1
        usage = expected.get("usage") or {}
        return JevSystemOneResult(
            answers=dict(expected["answers"]),  # type: ignore[arg-type]
            model=str(expected["model"]),
            latency_ms=float(expected["latency_ms"]),
            input_chars=int(expected["input_chars"]),
            usage=JevUsage(
                prompt_tokens=usage.get("prompt_tokens"),  # type: ignore[arg-type]
                completion_tokens=usage.get("completion_tokens"),  # type: ignore[arg-type]
                total_tokens=usage.get("total_tokens"),  # type: ignore[arg-type]
            ),
            raw={},
        )

    @property
    def remaining(self) -> int:
        return len(self._entries) - self._cursor


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
