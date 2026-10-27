//! Calibration formula tests — pinned, offline, deterministic.

use swe_gym::calibrate::{calibrate, CallSample};

#[test]
fn calibration_formula_is_pinned() {
    let samples = [
        CallSample {
            tokens: 400,
            latency_ms: 200,
        },
        CallSample {
            tokens: 450,
            latency_ms: 300,
        },
    ];
    // Anchor: 1 coin = 1000 tokens or 1000 ms. Max share over samples:
    // max(0.45, 0.3) → ceil = 1 coin → 1000 milli.
    let report = calibrate(&samples, 1_000, 1_000, 1_000);
    assert_eq!(report.samples, 2);
    assert_eq!(report.mean_tokens, 425.0);
    assert_eq!(report.median_latency_ms, 300);
    assert_eq!(report.proposed_tariff_milli, 1_000);
    assert_eq!(report.current_tariff_milli, 1_000);
    assert!((report.implied_coins_per_token - 1.0 / 425.0).abs() < 1e-9);
    assert!((report.implied_coins_per_second - 1.0 / 0.3).abs() < 1e-9);
}

#[test]
fn calibration_scales_with_usage() {
    let samples = [CallSample {
        tokens: 3_400,
        latency_ms: 200,
    }];
    // 3400 tokens / 1000 → 3.4 → ceil 4 coins.
    let report = calibrate(&samples, 1_000, 1_000, 1_000);
    assert_eq!(report.proposed_tariff_milli, 4_000);
}

#[test]
fn calibration_requires_samples_and_positive_anchors() {
    let empty: [CallSample; 0] = [];
    assert!(std::panic::catch_unwind(|| calibrate(&empty, 1_000, 1_000, 1_000)).is_err());
    let samples = [CallSample {
        tokens: 100,
        latency_ms: 100,
    }];
    assert!(std::panic::catch_unwind(|| calibrate(&samples, 0, 1_000, 1_000)).is_err());
    assert!(std::panic::catch_unwind(|| calibrate(&samples, 1_000, 0, 1_000)).is_err());
}
