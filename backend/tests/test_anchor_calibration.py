"""Tests for SSR anchor calibration gates and macro-accuracy."""

from __future__ import annotations

import pytest

from app.database.models import SsrAnchorCalibrationItem, SsrAnchorSet
from app.services.anchor_calibration import (
    ACCURACY_BLOCK_THRESHOLD,
    ACCURACY_OK_THRESHOLD,
    calibration_validation_status,
    clear_calibration_results,
    labels_missing_coverage,
    publish_needs_acknowledgement,
)
from app.services.ssr.accuracy import macro_accuracy
from app.serializers import utcnow


def test_macro_accuracy_per_label_mean():
    predicted = ["a", "b", "a", "c"]
    actual = ["a", "b", "b", "c"]
    assert macro_accuracy(predicted, actual) == pytest.approx(5 / 6)


def test_calibration_validation_status_stale_on_pool_revision():
    row = SsrAnchorSet(
        name="x",
        kind="tone",
        locale="sv",
        version="v1",
        labels=["a"],
        statements=["s"],
        status="draft",
        pool_revision=2,
        calibration_accuracy=0.8,
        calibration_tested_at=utcnow(),
        calibration_pool_revision=1,
        calibration_n_at_test=8,
    )
    assert calibration_validation_status(row, calibration_count=8) == "stale"


def test_calibration_validation_status_low_accuracy():
    row = SsrAnchorSet(
        name="x",
        kind="tone",
        locale="sv",
        version="v1",
        labels=["a"],
        statements=["s"],
        status="published",
        pool_revision=0,
        calibration_accuracy=0.5,
        calibration_tested_at=utcnow(),
        calibration_pool_revision=0,
        calibration_n_at_test=8,
    )
    assert calibration_validation_status(row, calibration_count=8) == "low"


def test_publish_needs_acknowledgement():
    assert publish_needs_acknowledgement(accuracy=0.5, missing_labels=[])
    assert publish_needs_acknowledgement(accuracy=0.8, missing_labels=["Neutral"])
    assert not publish_needs_acknowledgement(accuracy=0.8, missing_labels=[])
    assert not publish_needs_acknowledgement(accuracy=0.6, missing_labels=[])


def test_labels_missing_coverage():
    items = [
        SsrAnchorCalibrationItem(
            anchor_set_id=1,
            text="x",
            human_label="a",
            sort_order=0,
            created_at=utcnow(),
        )
    ]
    assert labels_missing_coverage(items, ["a", "b"]) == ["b"]


def test_clear_calibration_results():
    row = SsrAnchorSet(
        name="x",
        kind="tone",
        locale="sv",
        version="v1",
        labels=["a"],
        statements=["s"],
        status="draft",
        calibration_accuracy=0.9,
        calibration_tested_at=utcnow(),
        calibration_pool_revision=0,
        calibration_n_at_test=8,
    )
    clear_calibration_results(row)
    assert row.calibration_accuracy is None
    assert row.calibration_tested_at is None


def test_accuracy_threshold_constants():
    assert ACCURACY_BLOCK_THRESHOLD == 0.40
    assert ACCURACY_OK_THRESHOLD == 0.55
