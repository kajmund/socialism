"""Isolated GLiNER2 span proposer with process-wide model lifecycle.

The model loads lazily on first use and is shared for the process lifetime —
never reloaded per TextUnit or per research run. The heavy runtime
dependencies (torch, transformers, gliner2) are deliberately NOT backend
dependencies: they must be installed in the research runtime, and enabling
the proposer without them fails loudly (no fallback, no silent skip).

CPU inference runs in a worker thread so the event loop never blocks.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from app.config import settings

GlinerProposerReason = (
    "missing_dependencies",
    "load_failed",
    "inference_failed",
    "timeout",
    "invalid_labels",
)


class GlinerProposerError(Exception):
    """Typed proposer failure. Research treats this as fatal when enabled."""

    def __init__(self, message: str, *, reason: GlinerProposerReason) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ProposalUnit:
    """One bounded text unit the proposer may scan."""

    unit_id: str
    text: str


@dataclass(frozen=True)
class SpanProposal:
    span: str
    label: str


@dataclass(frozen=True)
class UnitProposals:
    unit_id: str
    proposals: tuple[SpanProposal, ...]


_model: object | None = None
_model_lock = threading.Lock()


def _load_model() -> object:
    """Load once per process under a lock. Raises loudly when unavailable."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from gliner2 import AutoExtractor  # deferred: heavy optional deps
        except ImportError as exc:
            raise GlinerProposerError(
                "gliner_span_proposer is enabled but gliner2 is not installed "
                "in the research runtime; install torch + transformers + gliner2",
                reason="missing_dependencies",
            ) from exc
        try:
            model = AutoExtractor.from_pretrained(settings.gliner_span_proposer.model)
        except Exception as exc:
            raise GlinerProposerError(
                f"failed to load GLiNER2 model {settings.gliner_span_proposer.model!r}: {exc}",
                reason="load_failed",
            ) from exc
        _model = model
        return model


def reset_model_cache() -> None:
    """Test seam: drop the cached model without importing the heavy deps."""
    global _model
    with _model_lock:
        _model = None


def _propose_sync(
    units: tuple[ProposalUnit, ...],
    labels: tuple[str, ...],
) -> list[UnitProposals]:
    extractor = _load_model()
    result: list[UnitProposals] = []
    for unit in units:
        try:
            raw = extractor.extract_entities(
                unit.text,
                entity_types=list(labels),
                threshold=settings.gliner_span_proposer.threshold,
                format_results=False,
            )
        except Exception as exc:
            raise GlinerProposerError(
                f"GLiNER2 inference failed for unit {unit.unit_id!r}: {exc}",
                reason="inference_failed",
            ) from exc
        spans: list[SpanProposal] = []
        for entry in raw.get("entities", []):
            for label, items in entry.items():
                for span in items:
                    spans.append(SpanProposal(span=span, label=label))
        result.append(UnitProposals(unit_id=unit.unit_id, proposals=tuple(spans)))
    return result


async def propose_spans(
    units: tuple[ProposalUnit, ...],
    labels: tuple[str, ...],
    *,
    timeout_seconds: float | None = None,
) -> list[UnitProposals]:
    """Propose spans for the given units. Fails loudly on any failure."""
    if not units:
        return []
    if not labels or any(not label.strip() for label in labels):
        raise GlinerProposerError("propose_spans requires non-empty labels",
                                  reason="invalid_labels")
    timeout = timeout_seconds if timeout_seconds is not None else settings.gliner_span_proposer.inference_timeout_seconds
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_propose_sync, units, labels),
            timeout=timeout,
        )
    except TimeoutError as exc:
        raise GlinerProposerError(
            f"GLiNER2 inference timed out after {timeout:.0f}s",
            reason="timeout",
        ) from exc
