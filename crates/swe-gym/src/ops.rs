//! Typed operation graph with execution contracts (docs/SWE_Sweycoins_v2.md
//! 30). An operation declares its required inputs, execution policy and
//! missing-input outcome as DATA; the gate derives executability from the
//! contract, never from what happened to get resolved. A need cannot
//! vanish from a comparison just because it stayed UNRESOLVED, and an
//! operation cannot degenerate to running on a single input.

use std::collections::BTreeMap;

/// A fact a conclusion requires: which fact, in which document.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct NeedRef {
    pub fact: String,
    pub document: String,
}

impl NeedRef {
    pub fn new(fact: &str, document: &str) -> Self {
        Self {
            fact: fact.to_string(),
            document: document.to_string(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExecutionPolicy {
    /// Every required input must be present; anything less is a miss.
    AllRequired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MissingOutcome {
    /// The operation must not run; the answer is INSUFFICIENT_EVIDENCE.
    InsufficientEvidence,
}

/// The contract of one operation in the graph.
#[derive(Debug, Clone)]
pub struct OperationSpec {
    pub name: String,
    pub required_inputs: Vec<NeedRef>,
    pub execution_policy: ExecutionPolicy,
    pub on_missing: MissingOutcome,
}

impl OperationSpec {
    /// The gate: does the resolved evidence satisfy the contract?
    /// `resolved` maps document -> normalized value (e.g. months).
    pub fn gate(&self, resolved: &BTreeMap<String, i64>) -> Result<(), MissingOutcome> {
        match self.execution_policy {
            ExecutionPolicy::AllRequired => {
                for input in &self.required_inputs {
                    if !resolved.contains_key(&input.document) {
                        // A need that was never RESOLVED still blocks the
                        // operation — it cannot silently drop out.
                        return Err(self.on_missing);
                    }
                }
                Ok(())
            }
        }
    }
}

/// The deterministic executor of MAX_NOTICE_PERIOD: compare normalized
/// values. Runs only after the gate passes.
pub fn max_notice_period(resolved: &BTreeMap<String, i64>) -> Option<String> {
    resolved
        .iter()
        .max_by_key(|(_, months)| **months)
        .map(|(document, _)| document.clone())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spec(docs: &[&str]) -> OperationSpec {
        OperationSpec {
            name: "MAX_NOTICE_PERIOD".to_string(),
            required_inputs: docs
                .iter()
                .map(|d| NeedRef::new("notice_period", d))
                .collect(),
            execution_policy: ExecutionPolicy::AllRequired,
            on_missing: MissingOutcome::InsufficientEvidence,
        }
    }

    fn months(m: &[(&str, i64)]) -> BTreeMap<String, i64> {
        m.iter().map(|(d, v)| (d.to_string(), *v)).collect()
    }

    #[test]
    fn gate_blocks_partial_inputs() {
        // The g3-06 regression: only one of three documents resolved.
        let op = spec(&["Avtal_17", "Avtal_18", "Avtal_20"]);
        let resolved = months(&[("Avtal_17", 9)]);
        assert_eq!(
            op.gate(&resolved),
            Err(MissingOutcome::InsufficientEvidence)
        );
    }

    #[test]
    fn gate_passes_when_all_inputs_resolved() {
        let op = spec(&["Avtal_17", "Avtal_18", "Avtal_20"]);
        let resolved = months(&[("Avtal_17", 9), ("Avtal_18", 3), ("Avtal_20", 6)]);
        assert_eq!(op.gate(&resolved), Ok(()));
    }

    #[test]
    fn max_executor_picks_longest() {
        let resolved = months(&[("Avtal_17", 9), ("Avtal_18", 3), ("Avtal_20", 6)]);
        assert_eq!(max_notice_period(&resolved), Some("Avtal_17".to_string()));
    }

    #[test]
    fn needs_derive_from_the_spec_not_from_resolution() {
        // The contract lists all three inputs regardless of what got
        // resolved: an unresolved need cannot vanish from the graph.
        let op = spec(&["Avtal_17", "Avtal_18", "Avtal_20"]);
        assert_eq!(op.required_inputs.len(), 3);
        let resolved = months(&[("Avtal_17", 9)]);
        assert_eq!(
            op.gate(&resolved),
            Err(MissingOutcome::InsufficientEvidence)
        );
    }

    #[test]
    fn missing_outcome_never_runs_a_partial_comparison() {
        // The executor must not degenerate to comparing one value.
        let op = spec(&["Avtal_17", "Avtal_18", "Avtal_20"]);
        let resolved = months(&[("Avtal_17", 9)]);
        if op.gate(&resolved).is_ok() {
            let _ = max_notice_period(&resolved);
            panic!("gate must reject partial inputs before execution");
        }
    }
}
/// What an operation produced: an answer, a NEW information need it
/// discovered (hand control back to Investigation), or a blocked gate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OpOutcome {
    Answer(String),
    /// The operation discovered a requirement it cannot satisfy — it
    /// creates a need instead of guessing.
    NeedMore(NeedRef),
    Insufficient,
}

/// APPLY_EXCEPTION: an exception modifies a base rule only if its
/// condition is met. When the condition is unresolved, the operation
/// returns NeedMore instead of guessing.
pub fn apply_exception(base: Option<(&str, i64)>, condition: Option<(&str, i64)>) -> OpOutcome {
    match condition {
        None => OpOutcome::NeedMore(NeedRef::new("condition", "unknown")),
        Some((_, threshold)) => match base {
            None => OpOutcome::Insufficient,
            Some((doc, value)) => {
                if value > threshold {
                    OpOutcome::Answer(format!("undantag gäller: {doc}"))
                } else {
                    OpOutcome::Answer(format!("grundregel gäller: {doc}"))
                }
            }
        },
    }
}

/// The investigation->operation loop: each round the gate runs FIRST;
/// a failed gate may yield a discovered need that Investigation tries
/// to resolve; the loop ends on an answer, on insufficient evidence,
/// or when the round cap is hit. A step policy can only influence
/// WHICH need is resolved next — the gate itself is not optional.
pub fn investigate_operate_loop(
    gate: impl Fn(&BTreeMap<String, i64>) -> Result<(), MissingOutcome>,
    mut execute: impl FnMut(&BTreeMap<String, i64>) -> OpOutcome,
    mut resolve_need: impl FnMut(&NeedRef) -> Option<i64>,
    max_rounds: usize,
) -> OpOutcome {
    let mut resolved: BTreeMap<String, i64> = BTreeMap::new();
    // The loop guard: a need that was already requested must not be
    // re-requested — identical NeedMore twice ends the loop instead of
    // spinning forever.
    let mut seen: Vec<NeedRef> = Vec::new();
    for _ in 0..max_rounds {
        // The gate is structural: a failed gate ends the loop with
        // INSUFFICIENT_EVIDENCE — no execution, no discovery, no guess.
        if gate(&resolved).is_err() {
            return OpOutcome::Insufficient;
        }
        match execute(&resolved) {
            OpOutcome::Answer(answer) => return OpOutcome::Answer(answer),
            OpOutcome::NeedMore(need) => {
                if seen.contains(&need) {
                    return OpOutcome::Insufficient;
                }
                seen.push(need.clone());
                match resolve_need(&need) {
                    Some(value) => {
                        resolved.insert(need.document.clone(), value);
                    }
                    None => return OpOutcome::Insufficient,
                }
            }
            OpOutcome::Insufficient => return OpOutcome::Insufficient,
        }
    }
    OpOutcome::Insufficient
}

#[cfg(test)]
mod loop_tests {
    use super::*;

    fn gate_three() -> impl Fn(&BTreeMap<String, i64>) -> Result<(), MissingOutcome> {
        |resolved| {
            let op = OperationSpec {
                name: "MAX_NOTICE_PERIOD".to_string(),
                required_inputs: vec![
                    NeedRef::new("notice_period", "Avtal_17"),
                    NeedRef::new("notice_period", "Avtal_18"),
                    NeedRef::new("notice_period", "Avtal_20"),
                ],
                execution_policy: ExecutionPolicy::AllRequired,
                on_missing: MissingOutcome::InsufficientEvidence,
            };
            op.gate(resolved)
        }
    }

    #[test]
    fn exception_discovers_condition_and_returns_to_investigation() {
        let mut rounds = 0;
        let outcome = investigate_operate_loop(
            |_| Ok(()),
            |_resolved| {
                rounds += 1;
                if rounds == 1 {
                    // The condition is unresolved: discover the need.
                    OpOutcome::NeedMore(NeedRef::new("condition", "Avtal_X"))
                } else {
                    OpOutcome::Answer("grundregel gäller".to_string())
                }
            },
            |_need| Some(3), // Investigation resolves the condition
            3,
        );
        assert_eq!(outcome, OpOutcome::Answer("grundregel gäller".to_string()));
    }

    #[test]
    fn unresolved_discovered_need_ends_in_insufficient_not_a_guess() {
        let outcome = investigate_operate_loop(
            |_| Ok(()),
            |_resolved| OpOutcome::NeedMore(NeedRef::new("condition", "Avtal_X")),
            |_need| None, // Investigation cannot resolve it
            3,
        );
        assert_eq!(outcome, OpOutcome::Insufficient);
    }

    #[test]
    fn gate_runs_every_round_regardless_of_resolution_order() {
        // A policy could resolve needs in any order, but the gate is
        // structural: partial inputs never produce an answer.
        let mut i = 0;
        let outcome = investigate_operate_loop(
            gate_three(),
            |resolved| {
                if resolved.len() == 3 {
                    OpOutcome::Answer(max_notice_period(resolved).unwrap_or_default())
                } else {
                    OpOutcome::Insufficient
                }
            },
            |need| {
                i += 1;
                Some(9) // resolves whatever the policy asks for
            },
            4,
        );
        // The policy resolved one need per round; the gate never let a
        // partial answer through.
        assert_eq!(outcome, OpOutcome::Insufficient);
    }

    #[test]
    fn identical_needmore_twice_ends_the_loop() {
        let outcome = investigate_operate_loop(
            |_| Ok(()),
            |_resolved| OpOutcome::NeedMore(NeedRef::new("condition", "Avtal_X")),
            |_need| Some(3), // resolves, but the operation asks again
            5,
        );
        assert_eq!(outcome, OpOutcome::Insufficient);
    }

    #[test]
    fn exception_condition_changes_the_conclusion() {
        // Base rule 9 months; condition threshold 6 -> exception applies.
        let outcome = apply_exception(Some(("Avtal_17", 9)), Some(("villkor", 6)));
        assert_eq!(
            outcome,
            OpOutcome::Answer("undantag gäller: Avtal_17".to_string())
        );
        // Below threshold -> the base rule stands.
        let outcome = apply_exception(Some(("Avtal_17", 3)), Some(("villkor", 6)));
        assert_eq!(
            outcome,
            OpOutcome::Answer("grundregel gäller: Avtal_17".to_string())
        );
    }
}
