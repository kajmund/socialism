//! Generic operations: typed contracts, the execution gate, and the outcome.
//!
//! An operation declares the facts it requires. The engine decides, from that
//! declaration and the resolved need states, whether the operation may run.
//! This is the part that must not be negotiable: a policy may choose *which*
//! permitted action runs next, but it can never make an under-specified
//! operation executable, and an operation can never fall back to a partial
//! comparison.
//!
//! The domain supplies the executors (what an operation computes and how facts
//! are normalised). It supplies them through [`execute`], which keeps the gate
//! structurally in front of every executor.

use std::fmt;

use crate::needs::{NeedRef, NeedStatus};

/// How an operation decides whether it may run.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ExecutionPolicy {
    /// Every declared input must be present and usable.
    AllRequired,
}

/// What happens when a declared input is not usable.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MissingOutcome {
    /// Do not run; the conclusion is INSUFFICIENT_EVIDENCE.
    InsufficientEvidence,
}

/// The contract of one operation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OperationSpec {
    pub name: String,
    pub required_inputs: Vec<NeedRef>,
    pub execution_policy: ExecutionPolicy,
    pub on_missing: MissingOutcome,
}

impl OperationSpec {
    pub fn new(name: impl Into<String>, required_inputs: Vec<NeedRef>) -> Self {
        Self {
            name: name.into(),
            required_inputs,
            execution_policy: ExecutionPolicy::AllRequired,
            on_missing: MissingOutcome::InsufficientEvidence,
        }
    }

    /// The gate: does the resolved evidence satisfy the contract?
    ///
    /// Returns every missing input, not just the first, so the abstention can
    /// say exactly what was missing.
    pub fn gate(&self, states: &[(NeedRef, NeedStatus)]) -> Result<(), GateFailure> {
        match self.execution_policy {
            ExecutionPolicy::AllRequired => {
                let missing: Vec<MissingInput> = self
                    .required_inputs
                    .iter()
                    .filter_map(|required| {
                        let status = states
                            .iter()
                            .find(|(need, _)| need == required)
                            .map(|(_, status)| *status)
                            .unwrap_or(NeedStatus::Unresolved);
                        if status.is_resolved() {
                            None
                        } else {
                            Some(MissingInput {
                                need: required.clone(),
                                status,
                            })
                        }
                    })
                    .collect();
                if missing.is_empty() {
                    Ok(())
                } else {
                    Err(GateFailure {
                        operation: self.name.clone(),
                        outcome: self.on_missing,
                        missing,
                    })
                }
            }
        }
    }
}

/// One declared input the gate could not accept.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MissingInput {
    pub need: NeedRef,
    pub status: NeedStatus,
}

/// Why an operation was not allowed to run.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GateFailure {
    pub operation: String,
    pub outcome: MissingOutcome,
    pub missing: Vec<MissingInput>,
}

impl fmt::Display for GateFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let names: Vec<String> = self
            .missing
            .iter()
            .map(|input| format!("{} ({})", input.need, input.status.as_str()))
            .collect();
        write!(
            f,
            "INSUFFICIENT_EVIDENCE: operation {} ALL_REQUIRED gate is missing {} required input(s): {}",
            self.operation,
            self.missing.len(),
            names.join(", ")
        )
    }
}

impl std::error::Error for GateFailure {}

/// What an operation produced.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OpOutcome {
    /// The operation ran and produced a value.
    Answer(String),
    /// The operation discovered a need its contract does not cover.
    NeedMore(NeedRef),
    /// The gate refused to run it.
    InsufficientEvidence(GateFailure),
}

/// Why an investigation stopped without an answer.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StopReason {
    /// The gate refused: at least one required input was missing.
    InsufficientEvidence(GateFailure),
    /// The operation asked for the identical need twice.
    RepeatedNeed(NeedRef),
    /// The round budget ran out before the operation could answer.
    RoundLimit(u32),
    /// The operation itself reported it could not decide.
    ExecutorGaveUp,
}

impl StopReason {
    /// The stable wire spelling a host reports to a caller.
    pub fn conclusion(&self) -> &'static str {
        match self {
            Self::InsufficientEvidence(_)
            | Self::RepeatedNeed(_)
            | Self::RoundLimit(_)
            | Self::ExecutorGaveUp => "INSUFFICIENT_EVIDENCE",
        }
    }

    pub fn detail(&self) -> String {
        match self {
            Self::InsufficientEvidence(failure) => failure.to_string(),
            Self::RepeatedNeed(need) => format!("INSUFFICIENT_EVIDENCE: repeated need {need}"),
            Self::RoundLimit(rounds) => {
                format!("INSUFFICIENT_EVIDENCE: no answer within {rounds} round(s)")
            }
            Self::ExecutorGaveUp => {
                "INSUFFICIENT_EVIDENCE: the operation could not decide from verified evidence"
                    .to_string()
            }
        }
    }
}

/// The result of investigating until the operation can answer.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Investigation {
    Answer(String),
    Stopped(StopReason),
}

impl Investigation {
    pub fn conclusion(&self) -> &'static str {
        match self {
            Self::Answer(_) => "answered",
            Self::Stopped(reason) => reason.conclusion(),
        }
    }
}

/// Run one operation under its gate, bounded by a round budget.
///
/// The gate runs **before** the executor on every round, including the first.
/// `resolve` attempts to satisfy a discovered need and returns whether it
/// succeeded.
pub fn execute<X, R>(
    spec: &OperationSpec,
    states: &mut Vec<(NeedRef, NeedStatus)>,
    mut executor: X,
    mut resolve: R,
    max_rounds: u32,
) -> Investigation
where
    X: FnMut() -> OpOutcome,
    R: FnMut(&NeedRef) -> Option<NeedStatus>,
{
    let mut seen: Vec<NeedRef> = Vec::new();
    for _ in 0..max_rounds {
        if let Err(failure) = spec.gate(states) {
            return Investigation::Stopped(StopReason::InsufficientEvidence(failure));
        }
        match executor() {
            OpOutcome::Answer(answer) => return Investigation::Answer(answer),
            OpOutcome::InsufficientEvidence(failure) => {
                return Investigation::Stopped(StopReason::InsufficientEvidence(failure));
            }
            OpOutcome::NeedMore(need) => {
                // The loop guard lives here, not in the caller: an operation
                // that keeps asking for the same fact can never progress.
                if seen.contains(&need) {
                    return Investigation::Stopped(StopReason::RepeatedNeed(need));
                }
                seen.push(need.clone());
                match resolve(&need) {
                    Some(status) => states.push((need, status)),
                    None => {
                        return Investigation::Stopped(StopReason::InsufficientEvidence(
                            GateFailure {
                                operation: spec.name.clone(),
                                outcome: spec.on_missing,
                                missing: vec![MissingInput {
                                    need,
                                    status: NeedStatus::Unresolved,
                                }],
                            },
                        ));
                    }
                }
            }
        }
    }
    Investigation::Stopped(StopReason::RoundLimit(max_rounds))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn need(fact: &str, subject: &str) -> NeedRef {
        NeedRef::new(fact, subject)
    }

    fn spec(subjects: &[&str]) -> OperationSpec {
        OperationSpec::new(
            "COMPARE",
            subjects
                .iter()
                .map(|subject| need("fact_a", subject))
                .collect(),
        )
    }

    fn all_resolved(spec: &OperationSpec) -> Vec<(NeedRef, NeedStatus)> {
        spec.required_inputs
            .iter()
            .map(|required| (required.clone(), NeedStatus::Resolved))
            .collect()
    }

    #[test]
    fn gate_blocks_partial_inputs() {
        let spec = spec(&["doc-a", "doc-b", "doc-c"]);
        let states = vec![(need("fact_a", "doc-a"), NeedStatus::Resolved)];
        let failure = spec.gate(&states).unwrap_err();
        assert_eq!(failure.missing.len(), 2);
        assert_eq!(failure.outcome, MissingOutcome::InsufficientEvidence);
        assert!(failure.to_string().contains("doc-b.fact_a"));
    }

    #[test]
    fn gate_passes_when_every_input_is_resolved() {
        let spec = spec(&["doc-a", "doc-b"]);
        assert!(spec.gate(&all_resolved(&spec)).is_ok());
    }

    #[test]
    fn an_unresolved_need_cannot_vanish_from_the_gate() {
        // The regression this type exists for: one of three resolved must never
        // make the operation look runnable.
        let spec = spec(&["doc-a", "doc-b", "doc-c"]);
        let mut states = vec![(need("fact_a", "doc-a"), NeedStatus::Resolved)];
        states.retain(|(need, _)| need.fact == "fact_a");
        assert_eq!(spec.required_inputs.len(), 3);
        assert!(spec.gate(&states).is_err());
    }

    #[test]
    fn ambiguous_is_not_accepted_by_the_gate() {
        let spec = spec(&["doc-a"]);
        let states = vec![(need("fact_a", "doc-a"), NeedStatus::Ambiguous)];
        assert!(spec.gate(&states).is_err());
    }

    #[test]
    fn executor_never_runs_on_partial_inputs() {
        let spec = spec(&["doc-a", "doc-b"]);
        let mut states = vec![(need("fact_a", "doc-a"), NeedStatus::Resolved)];
        let mut calls = 0;
        let outcome = execute(
            &spec,
            &mut states,
            || {
                calls += 1;
                OpOutcome::Answer("should not run".into())
            },
            |_| None,
            4,
        );
        assert_eq!(calls, 0, "the gate must reject before the executor runs");
        assert!(matches!(
            outcome,
            Investigation::Stopped(StopReason::InsufficientEvidence(_))
        ));
    }

    #[test]
    fn need_more_is_resolved_and_the_operation_reruns() {
        let spec = spec(&["doc-a"]);
        let mut states = all_resolved(&spec);
        let mut rounds = 0;
        let outcome = execute(
            &spec,
            &mut states,
            || {
                rounds += 1;
                if rounds == 1 {
                    OpOutcome::NeedMore(need("condition", "doc-x"))
                } else {
                    OpOutcome::Answer("rule applies".into())
                }
            },
            |_| Some(NeedStatus::Resolved),
            3,
        );
        assert_eq!(outcome.conclusion(), "answered");
        assert_eq!(rounds, 2);
    }

    #[test]
    fn an_unresolvable_discovered_need_ends_in_insufficient_evidence() {
        let spec = spec(&["doc-a"]);
        let mut states = all_resolved(&spec);
        let outcome = execute(
            &spec,
            &mut states,
            || OpOutcome::NeedMore(need("condition", "doc-x")),
            |_| None,
            3,
        );
        assert_eq!(outcome.conclusion(), "INSUFFICIENT_EVIDENCE");
    }

    #[test]
    fn identical_need_more_twice_ends_the_investigation() {
        let spec = spec(&["doc-a"]);
        let mut states = all_resolved(&spec);
        let outcome = execute(
            &spec,
            &mut states,
            || OpOutcome::NeedMore(need("condition", "doc-x")),
            |_| Some(NeedStatus::Resolved),
            5,
        );
        assert!(matches!(
            outcome,
            Investigation::Stopped(StopReason::RepeatedNeed(_))
        ));
    }

    #[test]
    fn the_gate_runs_every_round() {
        let spec = spec(&["doc-a", "doc-b"]);
        let mut states = vec![(need("fact_a", "doc-a"), NeedStatus::Resolved)];
        let outcome = execute(
            &spec,
            &mut states,
            || OpOutcome::Answer("never".into()),
            |_| Some(NeedStatus::Resolved),
            4,
        );
        // doc-b was never resolved because the executor never ran to discover it.
        assert_eq!(outcome.conclusion(), "INSUFFICIENT_EVIDENCE");
    }

    #[test]
    fn round_limit_is_a_clean_stop() {
        let spec = spec(&[]);
        let mut states = vec![];
        let mut rounds = 0;
        let outcome = execute(
            &spec,
            &mut states,
            || {
                rounds += 1;
                OpOutcome::NeedMore(need("more", &format!("doc-{rounds}")))
            },
            |_| Some(NeedStatus::Resolved),
            3,
        );
        assert_eq!(outcome.conclusion(), "INSUFFICIENT_EVIDENCE");
        assert!(matches!(
            outcome,
            Investigation::Stopped(StopReason::RoundLimit(3))
        ));
    }

    #[test]
    fn every_stop_reason_reports_insufficient_evidence() {
        let spec = spec(&["doc-a"]);
        let failure = spec.gate(&[]).unwrap_err();
        for reason in [
            StopReason::InsufficientEvidence(failure.clone()),
            StopReason::RepeatedNeed(need("x", "doc-x")),
            StopReason::RoundLimit(1),
            StopReason::ExecutorGaveUp,
        ] {
            assert_eq!(reason.conclusion(), "INSUFFICIENT_EVIDENCE");
            assert!(reason.detail().starts_with("INSUFFICIENT_EVIDENCE"));
        }
        assert_eq!(Investigation::Answer("x".into()).conclusion(), "answered");
    }
}
