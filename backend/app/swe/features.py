"""Trusted host context and per-customer/feature catalog paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.swe.errors import SwdValidationError
from app.swe.schema import CUSTOMER_ID_PATTERN, FEATURE_IDS

CUSTOMER_ID_RE = re.compile(CUSTOMER_ID_PATTERN)


@dataclass(frozen=True)
class WorkflowHostContext:
    """Customer and top-level feature. Never taken from YAML or model output."""

    customer_id: str
    feature_id: str

    def __post_init__(self) -> None:
        if not CUSTOMER_ID_RE.fullmatch(self.customer_id):
            raise SwdValidationError(
                f"invalid customer_id {self.customer_id!r}",
                path="host.customer_id",
            )
        if self.feature_id not in FEATURE_IDS:
            raise SwdValidationError(
                f"unknown feature_id {self.feature_id!r}",
                path="host.feature_id",
            )


def workflow_catalog_dir(root: Path, context: WorkflowHostContext) -> Path:
    """OverGraph catalog directory for one customer and owning feature."""
    return root / "workflows" / f"customer_{context.customer_id}" / context.feature_id
