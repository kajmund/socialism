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
