"""Settings for the optional GLiNER2 span proposer (off by default).

Kept as a nested settings model so ``backend/app/config.py`` stays the
single source of truth without growing; env overrides use the nested
pydantic-settings form (``GLINER_SPAN_PROPOSER__ENABLED`` etc.).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GlinerSpanProposerSettings(BaseModel):
    # Global switch. Off by default; runs opt in per research run via the
    # attempt's configuration_snapshot key "gliner_span_proposer".
    enabled: bool = False
    model: str = "fastino/gliner2.5-multi-v1"
    threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    max_excerpt_chars: int = Field(default=4000, ge=256, le=16_000)
    max_units_per_need: int = Field(default=8, ge=1, le=64)
    max_spans_per_unit: int = Field(default=12, ge=1, le=64)
    inference_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
