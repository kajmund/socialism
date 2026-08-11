"""SSR anchor calibration: macro-accuracy, publish gates, validation status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SsrAnchorCalibrationItem, SsrAnchorSet
from app.services.anchor_pool import centroid_vectors_for_set
from app.services.anchor_store import calibration_items, row_to_anchor_set
from app.services.playground import rate_case
from app.services.ssr.accuracy import macro_accuracy
from app.serializers import utcnow

MIN_CALIBRATION_ITEMS = 8
ACCURACY_BLOCK_THRESHOLD = 0.40
ACCURACY_OK_THRESHOLD = 0.55

CalibrationValidationStatus = Literal["untested", "ok", "stale", "low"]


class PublishGateError(ValueError):
    """Publish blocked until calibration requirements are met."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        accuracy: float | None = None,
        missing_labels: list[str] | None = None,
        calibration_count: int = 0,
        requires_acknowledgement: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.accuracy = accuracy
        self.missing_labels = list(missing_labels or [])
        self.calibration_count = calibration_count
        self.requires_acknowledgement = requires_acknowledgement


def labels_missing_coverage(
    items: list[SsrAnchorCalibrationItem],
    labels: list[str],
) -> list[str]:
    covered = {item.human_label for item in items}
    return [lab for lab in labels if lab not in covered]


def calibration_validation_status(
    row: SsrAnchorSet,
    *,
    calibration_count: int,
) -> CalibrationValidationStatus:
    if row.calibration_tested_at is None or row.calibration_accuracy is None:
        return "untested"
    pool_rev = int(row.pool_revision or 0)
    tested_pool = row.calibration_pool_revision
    tested_n = row.calibration_n_at_test
    if tested_pool is None or tested_n is None:
        return "untested"
    if pool_rev != int(tested_pool) or calibration_count != int(tested_n):
        return "stale"
    if float(row.calibration_accuracy) < ACCURACY_OK_THRESHOLD:
        return "low"
    return "ok"


def validation_snapshot(
    row: SsrAnchorSet,
    *,
    calibration_count: int,
) -> dict:
    status = calibration_validation_status(row, calibration_count=calibration_count)
    tested_at = row.calibration_tested_at
    return {
        "anchor_set_id": int(row.id),
        "name": row.name,
        "kind": row.kind,
        "validation_status": status,
        "accuracy": row.calibration_accuracy,
        "tested_at": tested_at.isoformat() if isinstance(tested_at, datetime) else None,
        "pool_revision": int(row.pool_revision or 0),
        "calibration_pool_revision": row.calibration_pool_revision,
        "calibration_item_count": calibration_count,
        "calibration_n_at_test": row.calibration_n_at_test,
        "publish_override": bool(row.calibration_publish_override),
    }


def clear_calibration_results(row: SsrAnchorSet) -> None:
    row.calibration_accuracy = None
    row.calibration_tested_at = None
    row.calibration_pool_revision = None
    row.calibration_n_at_test = None


async def run_calibration_test(
    session: AsyncSession,
    row: SsrAnchorSet,
    *,
    temperature: float,
    persist: bool = True,
) -> dict:
    """Rate calibration corpus against centroid anchors; optionally persist metrics."""
    items = await calibration_items(session, row.id)
    if not items:
        raise PublishGateError(
            "No calibration items on this anchor set",
            code="calibration_empty",
            calibration_count=0,
        )

    texts = [item.text for item in items]
    human_labels = [item.human_label for item in items]
    anchor = row_to_anchor_set(row)
    anchor_vectors = await centroid_vectors_for_set(session, row)
    result = await rate_case(
        texts,
        dimension=row.kind,  # type: ignore[arg-type]
        locale=row.locale,
        labels=list(anchor.labels),
        statements=list(anchor.statements),
        temperature=temperature,
        human_labels=human_labels,
        anchor_vectors=anchor_vectors,
    )
    predicted = [row_["predicted_label"] for row_ in result["per_text"]]
    accuracy = macro_accuracy(predicted, human_labels)
    missing = labels_missing_coverage(items, list(anchor.labels))

    if persist:
        row.calibration_accuracy = round(accuracy, 4)
        row.calibration_tested_at = utcnow()
        row.calibration_pool_revision = int(row.pool_revision or 0)
        row.calibration_n_at_test = len(items)

    return {
        **result,
        "macro_accuracy": round(accuracy, 4),
        "missing_labels": missing,
        "calibration_count": len(items),
        "validation_status": calibration_validation_status(
            row,
            calibration_count=len(items),
        )
        if persist
        else "untested",
    }


def publish_needs_acknowledgement(
    *,
    accuracy: float,
    missing_labels: list[str],
) -> bool:
    if accuracy < ACCURACY_BLOCK_THRESHOLD:
        return False
    return bool(missing_labels) or accuracy < ACCURACY_OK_THRESHOLD


async def assert_publish_allowed(
    session: AsyncSession,
    row: SsrAnchorSet,
    *,
    temperature: float,
    acknowledge_warnings: bool,
) -> dict:
    """Run calibration test and enforce publish gates."""
    if row.status == "published":
        raise PublishGateError(
            "Anchor set is already published",
            code="already_published",
        )

    items = await calibration_items(session, row.id)
    count = len(items)
    if count < MIN_CALIBRATION_ITEMS:
        raise PublishGateError(
            f"At least {MIN_CALIBRATION_ITEMS} calibration items required (have {count})",
            code="calibration_too_few",
            calibration_count=count,
        )

    test_result = await run_calibration_test(
        session,
        row,
        temperature=temperature,
        persist=False,
    )
    accuracy = float(test_result["macro_accuracy"])
    missing = list(test_result["missing_labels"])

    if accuracy < ACCURACY_BLOCK_THRESHOLD:
        raise PublishGateError(
            f"Macro-accuracy {accuracy:.0%} is below {ACCURACY_BLOCK_THRESHOLD:.0%} "
            f"— improve calibration before publishing",
            code="accuracy_too_low",
            accuracy=accuracy,
            missing_labels=missing,
            calibration_count=count,
            requires_acknowledgement=False,
        )

    if publish_needs_acknowledgement(accuracy=accuracy, missing_labels=missing):
        if not acknowledge_warnings:
            raise PublishGateError(
                "Publish requires acknowledgement of calibration warnings",
                code="acknowledgement_required",
                accuracy=accuracy,
                missing_labels=missing,
                calibration_count=count,
                requires_acknowledgement=True,
            )

    return test_result


async def finalize_publish_calibration(
    session: AsyncSession,
    row: SsrAnchorSet,
    *,
    temperature: float,
    acknowledge_warnings: bool,
) -> None:
    await run_calibration_test(session, row, temperature=temperature, persist=True)
    # Set only when publish passed via soft-gate acknowledgement (assert_publish_allowed
    # rejects acknowledge_warnings for accuracy below ACCURACY_BLOCK_THRESHOLD).
    row.calibration_publish_override = acknowledge_warnings


async def anchor_validation_for_report(
    session: AsyncSession,
    *,
    tone_row: SsrAnchorSet,
    style_row: SsrAnchorSet,
) -> dict[str, dict]:
    tone_items = await calibration_items(session, tone_row.id)
    style_items = await calibration_items(session, style_row.id)
    return {
        "tone": validation_snapshot(tone_row, calibration_count=len(tone_items)),
        "style": validation_snapshot(style_row, calibration_count=len(style_items)),
    }


__all__ = [
    "anchor_validation_for_report",
    "ACCURACY_BLOCK_THRESHOLD",
    "ACCURACY_OK_THRESHOLD",
    "MIN_CALIBRATION_ITEMS",
    "CalibrationValidationStatus",
    "PublishGateError",
    "assert_publish_allowed",
    "calibration_validation_status",
    "clear_calibration_results",
    "finalize_publish_calibration",
    "labels_missing_coverage",
    "macro_accuracy",
    "publish_needs_acknowledgement",
    "run_calibration_test",
    "validation_snapshot",
]
