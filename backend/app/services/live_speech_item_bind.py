"""Bind OpenAI transcription item IDs to local VAD utterances."""

from __future__ import annotations


class ProviderItemBinder:
    """Correlate provider-generated STT item IDs with VAD start/commit order.

    The browser ``input_item_id`` is not the OpenAI ``item_id``. A new provider
    id attaches to the current utterance. A late id that appears after a newer
    utterance started, while an earlier commit never got a provider id, is
    rejected instead of being treated as the current turn.
    """

    def __init__(self) -> None:
        self._current: str | None = None
        self._commit_seq = 0
        self._seq_for: dict[str, int] = {}
        self._bound: dict[str, tuple[int, str]] = {}
        self._claimed: set[str] = set()

    def reset(self) -> None:
        self._current = None
        self._commit_seq = 0
        self._seq_for.clear()
        self._bound.clear()
        self._claimed.clear()

    def start_utterance(self, utterance_id: str) -> None:
        self._current = utterance_id
        self._seq_for.setdefault(utterance_id, self._commit_seq)

    def commit(self, sequence: int) -> None:
        utterance = self._current
        if utterance is None:
            return
        self._commit_seq = sequence
        self._seq_for[utterance] = sequence
        for item_id, (_seq, uid) in list(self._bound.items()):
            if uid == utterance:
                self._bound[item_id] = (sequence, uid)

    def observe(self, item_id: str, *, final: bool) -> tuple[int, str] | None:
        if not item_id:
            return None
        existing = self._bound.get(item_id)
        if existing is not None:
            return existing
        utterance = self._current
        if utterance is None:
            self.start_utterance(item_id)
            utterance = item_id
        if final and self._has_unbound_previous():
            return None
        if utterance in self._claimed:
            return None
        bound = (self._seq_for.get(utterance, self._commit_seq), utterance)
        self._bound[item_id] = bound
        self._claimed.add(utterance)
        return bound

    def _has_unbound_previous(self) -> bool:
        return any(uid != self._current and uid not in self._claimed for uid in self._seq_for)
