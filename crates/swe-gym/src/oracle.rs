//! Exact DP oracle for the synthetic environment — the diagnostic upper
//! bound (v1's C* counterpart).
//!
//! Budget only decreases, so the MDP is acyclic: one backward pass over
//! (budget, tiers) with memoization yields the optimal value exactly.
//! Pause/Stop are omitted (strictly dominated: they only forfeit optional
//! future actions), and no-gain investments are skipped for the same
//! reason, so this is a true upper bound on every policy in the env.
//!
//! The oracle is never part of the learner's training data — it exists to
//! (a) run the calibration gate (measure signal first) and (b) interpret
//! results.

use crate::env::{gain_tiers, terminal_reward, EnvConfig, STRATEGY_COUNT};
use std::collections::HashMap;
use swe_budget::Amount;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
struct State {
    budget_coins: u8,
    tiers: [u8; STRATEGY_COUNT],
}

struct Dp {
    config: EnvConfig,
    qtype: u8,
    total_coins: u8,
    memo: HashMap<State, i64>,
}

impl Dp {
    fn value(&mut self, state: State) -> i64 {
        if let Some(v) = self.memo.get(&state) {
            return *v;
        }
        let spent = (self.total_coins - state.budget_coins) as u64 * 1_000;
        let mut best = terminal_reward(&self.config, self.qtype, &state.tiers, spent);
        for s in 0..STRATEGY_COUNT {
            for amount_coins in [1u8, 5, 10, 20] {
                if amount_coins > state.budget_coins {
                    continue;
                }
                let amount_milli = amount_coins as u64 * 1_000;
                let gained = gain_tiers(&self.config, self.qtype, s, &state.tiers, amount_milli);
                if gained == 0 {
                    continue; // dominated: spending for zero progress
                }
                let mut tiers = state.tiers;
                tiers[s] += gained;
                let next = State {
                    budget_coins: state.budget_coins - amount_coins,
                    tiers,
                };
                let v = self.value(next);
                if v > best {
                    best = v;
                }
            }
        }
        self.memo.insert(state, best);
        best
    }
}

/// Optimal expected value of the question, in milli Sweycoins (deterministic
/// env, so expectation = value). Budget must be a whole-coin multiple.
pub fn oracle_value(config: &EnvConfig, qtype: u8, budget_milli: Amount) -> i64 {
    assert!(
        budget_milli % 1_000 == 0 && budget_milli / 1_000 <= 255,
        "oracle budget must be a coin multiple below 256 coins"
    );
    let mut dp = Dp {
        config: config.clone(),
        qtype,
        total_coins: (budget_milli / 1_000) as u8,
        memo: HashMap::new(),
    };
    let start = State {
        budget_coins: dp.total_coins,
        tiers: [0; STRATEGY_COUNT],
    };
    dp.value(start)
}

/// The total cost of one optimal-value path — the stop-decision reference:
/// how much a policy that achieves the oracle value should spend.
pub fn oracle_policy_cost(config: &EnvConfig, qtype: u8, budget_milli: Amount) -> Amount {
    let mut dp = Dp {
        config: config.clone(),
        qtype,
        total_coins: (budget_milli / 1_000) as u8,
        memo: HashMap::new(),
    };
    let mut state = State {
        budget_coins: dp.total_coins,
        tiers: [0; STRATEGY_COUNT],
    };
    let mut spent = 0;
    // Walk one optimal path: pick the first action whose continuation
    // reaches the state's optimal value (ties -> finish).
    loop {
        let target = dp.value(state);
        let spent_here = (dp.total_coins - state.budget_coins) as u64 * 1_000;
        if target == terminal_reward(&config, qtype, &state.tiers, spent_here) {
            return spent;
        }
        let mut found = false;
        for s in 0..STRATEGY_COUNT {
            for amount_coins in [1u8, 5, 10, 20] {
                if amount_coins > state.budget_coins {
                    continue;
                }
                let amount_milli = amount_coins as u64 * 1_000;
                let gained = gain_tiers(&config, qtype, s, &state.tiers, amount_milli);
                if gained == 0 {
                    continue;
                }
                let mut tiers = state.tiers;
                tiers[s] += gained;
                let next = State {
                    budget_coins: state.budget_coins - amount_coins,
                    tiers,
                };
                if dp.value(next) == target {
                    state = next;
                    spent += amount_milli;
                    found = true;
                    break;
                }
            }
            if found {
                break;
            }
        }
        assert!(found, "optimal path must continue or finish");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::env::default_config;

    #[test]
    fn t3_oracle_is_c4_alone() {
        // t3: only C reaches full quality cheaply; anything else is
        // strictly worse once quality is capped at 1.0.
        let config = default_config();
        let v = oracle_value(&config, 3, 100_000);
        assert_eq!(v, 190_000); // 2.0 x 1.0 x 100k - 10k
    }

    #[test]
    fn oracle_never_exceeds_full_value_minus_floor() {
        let config = default_config();
        for qtype in 0..4 {
            let v = oracle_value(&config, qtype, 100_000);
            assert!(v > 0, "type {qtype} should be solvable profitably");
            assert!(v <= 200_000);
        }
    }

    #[test]
    fn zero_budget_is_zero_value() {
        let config = default_config();
        assert_eq!(oracle_value(&config, 0, 0), 0);
    }
}
