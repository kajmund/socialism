//! Tariff calibration from measured resource use.
//!
//! The frozen bench uses experimental prices (scan 1, deep 10). This module
//! derives prices from measured call samples — token usage and wall-clock
//! latency — under a stated anchor, so a policy optimizing Sweycoins is
//! optimizing real resources, not an arbitrary table.
//!
//! Anchors are explicit inputs, never hidden defaults. The report states the
//! implied resource cost of the current prices alongside the proposal.

use swe_budget::Amount;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CallSample {
    /// Total tokens (input + output).
    pub tokens: u64,
    /// Wall-clock latency in milliseconds.
    pub latency_ms: u64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CalibrationReport {
    pub samples: usize,
    pub mean_tokens: f64,
    pub median_latency_ms: u64,
    /// Proposed tariff under the anchor: ceil(max(tokens/anchor_tokens,
    /// latency/anchor_ms)), in thousandths of a Sweycoin.
    pub proposed_tariff_milli: Amount,
    /// What the current tariff implies: coins per token and coins per second.
    pub current_tariff_milli: Amount,
    pub implied_coins_per_token: f64,
    pub implied_coins_per_second: f64,
}

/// Derive a tariff from samples.
///
/// `anchor_tokens_per_coin` and `anchor_ms_per_coin` define what one Sweycoin
/// buys: the call's cost in coins is the larger of its token share and its
/// time share. `current_tariff_milli` is the frozen price being compared.
pub fn calibrate(
    samples: &[CallSample],
    anchor_tokens_per_coin: u64,
    anchor_ms_per_coin: u64,
    current_tariff_milli: Amount,
) -> CalibrationReport {
    assert!(!samples.is_empty(), "calibration requires samples");
    assert!(anchor_tokens_per_coin > 0 && anchor_ms_per_coin > 0);
    let mean_tokens = samples
        .iter()
        .map(|sample| sample.tokens as f64)
        .sum::<f64>()
        / samples.len() as f64;
    let mut latencies: Vec<u64> = samples.iter().map(|sample| sample.latency_ms).collect();
    latencies.sort_unstable();
    let median_latency_ms = latencies[latencies.len() / 2];
    let max_share = |tokens: u64, latency_ms: u64| -> f64 {
        (tokens as f64 / anchor_tokens_per_coin as f64)
            .max(latency_ms as f64 / anchor_ms_per_coin as f64)
    };
    let proposed_tariff_milli = (samples
        .iter()
        .map(|sample| max_share(sample.tokens, sample.latency_ms))
        .fold(0.0_f64, f64::max)
        .ceil() as Amount)
        .max(1)
        * 1_000;
    let implied_coins_per_token = current_tariff_milli as f64 / 1_000.0 / mean_tokens.max(1.0);
    let implied_coins_per_second =
        current_tariff_milli as f64 / 1_000.0 / (median_latency_ms.max(1) as f64 / 1_000.0);
    CalibrationReport {
        samples: samples.len(),
        mean_tokens,
        median_latency_ms,
        proposed_tariff_milli,
        current_tariff_milli,
        implied_coins_per_token,
        implied_coins_per_second,
    }
}
