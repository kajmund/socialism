//! A/B benchmark harness: executes a strategy's branch plans against the
//! swe-native kernel with one shared Sweycoin ledger.
//!
//! The runtime enforces the caps; strategies only propose the split. Branches
//! run interleaved (round-robin, one provider call per step) — deterministic,
//! and the same shape a single-threaded event loop would use. Providers plug
//! in behind the `ResearchProvider` seam: the synthetic corpus by default,
//! live JEV/LLM services or replay fixtures when asked.

use std::collections::HashSet;

use swe_native::{
    parse_json_str, sha256_hex, start_run, Effect, Json, RuntimeError, StepOutcome, WorkflowMachine,
};

use crate::driver::{build_chain_document_for, build_chunk_input_for, CallRecord};
use crate::ledger::{Amount, Ledger, LedgerError};
use crate::provider::ResearchProvider;
use crate::strategy::{
    BranchPlan, Continuation, Observations, Question, ScanDecision, ScanState, Strategy, Tariffs,
};

pub const RUN_ID: &str = "bench";

#[derive(Clone, Debug)]
pub struct ArmReport {
    pub strategy: &'static str,
    /// Diagnostic arms (oracle) are ceilings, never contenders.
    pub diagnostic: bool,
    pub solved: bool,
    pub found: Vec<String>,
    pub required: usize,
    pub spent_milli: Amount,
    pub leftover_milli: Amount,
    pub calls: Vec<CallRecord>,
    /// (account, chunk) — loud budget denials.
    pub denied: Vec<(String, String)>,
    pub ledger_events: usize,
    pub machine_events: usize,
    pub ledger: Ledger,
}

struct LiveBranch {
    account: String,
    machine: WorkflowMachine,
    outcome: StepOutcome,
    finished: bool,
}

struct Harness<'a> {
    run_id: &'a str,
    ledger: Ledger,
    provider: &'a dyn ResearchProvider,
    tariffs: &'a Tariffs,
    required: usize,
    found: HashSet<String>,
    calls: Vec<CallRecord>,
    denied: Vec<(String, String)>,
    machine_events: usize,
}

/// Run one strategy (arm) on one question with a hard total budget, using the
/// question's synthetic corpus provider.
pub fn run_arm(
    strategy: &mut dyn Strategy,
    question: &Question,
    total_budget_milli: Amount,
    tariffs: &Tariffs,
) -> ArmReport {
    let corpus = question.corpus();
    run_arm_with_provider(strategy, question, total_budget_milli, tariffs, &corpus)
}

/// Run one strategy (arm) with an explicit provider (live service, replay
/// fixture, recording wrapper). This is the realism seam: everything else is
/// identical.
pub fn run_arm_with_provider(
    strategy: &mut dyn Strategy,
    question: &Question,
    total_budget_milli: Amount,
    tariffs: &Tariffs,
    provider: &dyn ResearchProvider,
) -> ArmReport {
    // A question may pin its own budget; otherwise the caller's budget rules.
    let total_budget_milli = if question.budget_milli > 0 {
        question.budget_milli
    } else {
        total_budget_milli
    };
    let mut plans = strategy.plan(&question.view, total_budget_milli, tariffs);

    let mut ledger = Ledger::new();
    ledger
        .allocate(
            RUN_ID,
            "root",
            total_budget_milli,
            &format!("{}:alloc", strategy.name()),
        )
        .expect("run allocation");

    let mut allocated = 0;
    for plan in &plans {
        if plan.start_budget_milli > 0 {
            ledger
                .transfer(
                    "root",
                    &plan.account,
                    plan.start_budget_milli,
                    &format!("{}:plan:{}", strategy.name(), plan.account),
                )
                .expect("plans must fit inside the run budget");
        }
        allocated += plan.start_budget_milli;
    }
    assert!(
        allocated <= total_budget_milli,
        "plans may not exceed the run cap"
    );

    let mut harness = Harness {
        run_id: RUN_ID,
        ledger,
        provider,
        tariffs,
        required: question.view.required_coverage,
        found: HashSet::new(),
        calls: Vec::new(),
        denied: Vec::new(),
        machine_events: 0,
    };

    match strategy.continuation() {
        Continuation::Sequential => run_sequential(&mut harness, strategy, &mut plans),
        Continuation::ParallelEqual => run_parallel(&mut harness, &plans),
    }

    let leftover_milli: Amount = harness
        .ledger
        .balances()
        .values()
        .map(|balance| balance.available())
        .sum();
    let mut found: Vec<String> = harness.found.into_iter().collect();
    found.sort();

    ArmReport {
        strategy: strategy.name(),
        diagnostic: strategy.diagnostic(),
        solved: found.len() >= question.view.required_coverage,
        found,
        required: question.view.required_coverage,
        spent_milli: total_budget_milli - leftover_milli,
        leftover_milli,
        ledger_events: harness.ledger.events().len(),
        machine_events: harness.machine_events,
        calls: harness.calls,
        denied: harness.denied,
        ledger: harness.ledger,
    }
}

/// Sequential execution: branches in plan order; the first branch scans in
/// document order, escalation targets chunks not yet found; leftover budget of
/// a finished branch flows to the next branch's account. Between branches the
/// strategy may revise its remaining plans (facit-free observations only) —
/// that hook is the whole difference between arm A and arm C.
fn run_sequential(harness: &mut Harness, strategy: &mut dyn Strategy, plans: &mut [BranchPlan]) {
    for index in 0..plans.len() {
        if harness.solved() {
            break;
        }
        if index >= 1 {
            let observations = harness.observations();
            strategy.revise(index - 1, &observations, plans, harness.tariffs);
        }
        let plan = &plans[index];
        let candidates: Vec<String> = if index == 0 {
            plan.chunks.clone()
        } else {
            plan.chunks
                .iter()
                .filter(|chunk| !harness.found.contains(*chunk))
                .cloned()
                .collect()
        };
        if candidates.is_empty() {
            continue;
        }
        let mut branch = harness.spawn(plan, &candidates);
        while !branch.finished {
            harness.step_one(&mut branch);
            if harness.solved() {
                break;
            }
            // The scan phase (first branch) has a per-step checkpoint: the
            // strategy may stop scanning and escalate. Abandoning the branch
            // drops the rest of its chain; the unspent scan budget flows to
            // the next branch below.
            if index == 0 && !branch.finished {
                let scanned = harness
                    .calls
                    .iter()
                    .filter(|call| call.provider == "scan")
                    .count();
                let remaining = plan.chunks.len().saturating_sub(scanned);
                let state = harness.scan_state(remaining);
                if strategy.observe_scan(&state) == ScanDecision::Escalate {
                    branch.finished = true;
                }
            }
        }
        if let Some(next) = plans.get(index + 1) {
            harness.transfer_leftover(
                &plan.account,
                &next.account,
                &format!("{}:cont:{}-{}", harness.run_id, index, next.account),
            );
        }
    }
}

/// Arm B execution: all branches interleaved round-robin; a finished branch's
/// leftover budget is transferred to the first still-live branch.
fn run_parallel(harness: &mut Harness, plans: &[BranchPlan]) {
    let mut branches: Vec<LiveBranch> = plans
        .iter()
        .map(|plan| harness.spawn(plan, &plan.chunks))
        .collect();
    loop {
        if harness.solved() || branches.iter().all(|branch| branch.finished) {
            break;
        }
        let mut progress = false;
        for branch in branches.iter_mut() {
            if branch.finished {
                continue;
            }
            harness.step_one(branch);
            progress = true;
            if harness.solved() {
                break;
            }
        }
        if !progress {
            break;
        }
        let live_target = branches
            .iter()
            .find(|branch| !branch.finished)
            .map(|branch| branch.account.clone());
        let sources: Vec<(String, String)> = branches
            .iter()
            .filter(|branch| branch.finished && harness.account_available(&branch.account) > 0)
            .map(|branch| (branch.account.clone(), harness.run_id.to_string()))
            .collect();
        if let Some(target) = live_target {
            for (account, run_id) in sources {
                harness.transfer_leftover(
                    &account,
                    &target,
                    &format!("{run_id}:cont:{account}-{target}"),
                );
            }
        }
    }
}

impl<'a> Harness<'a> {
    fn solved(&self) -> bool {
        self.found.len() >= self.required
    }

    /// Facit-free observations for a strategy's revision hook: sorted found
    /// chunks, scan confidence per chunk and the coverage target. Never the
    /// answer key.
    fn observations(&self) -> Observations {
        let mut found: Vec<String> = self.found.iter().cloned().collect();
        found.sort();
        let mut scan_scores: Vec<(String, u32)> = self
            .calls
            .iter()
            .filter(|call| call.provider == "scan")
            .map(|call| (call.chunk.clone(), call.score_bp))
            .collect();
        scan_scores.sort();
        Observations {
            found,
            required: self.required,
            scan_scores,
        }
    }

    /// Facit-free scan checkpoint state for the per-step hook.
    fn scan_state(&self, remaining: usize) -> ScanState {
        let scanned = self
            .calls
            .iter()
            .filter(|call| call.provider == "scan")
            .count();
        let (last_choice, last_score_bp) = self
            .calls
            .last()
            .map(|call| (call.choice.clone(), call.score_bp))
            .unwrap_or_else(|| ("inget".into(), 0));
        let best_score_bp = self
            .calls
            .iter()
            .map(|call| call.score_bp)
            .max()
            .unwrap_or(0);
        ScanState {
            scanned,
            remaining,
            found: self.found.len(),
            required: self.required,
            last_choice,
            last_score_bp,
            best_score_bp,
        }
    }

    fn account_available(&self, account: &str) -> Amount {
        self.ledger.balance(account).available()
    }

    fn transfer_leftover(&mut self, from: &str, to: &str, key: &str) -> Amount {
        let amount = self.account_available(from);
        if amount > 0 {
            self.ledger
                .transfer(from, to, amount, key)
                .expect("leftover transfer preserves the ledger");
        }
        amount
    }

    /// Create a live kernel machine for a branch: a provider chain over the
    /// candidate chunks, in the plan's order.
    fn spawn(&mut self, plan: &BranchPlan, candidates: &[String]) -> LiveBranch {
        let document = build_chain_document_for(plan.provider.as_str(), candidates.len());
        let document = parse_json_str(&document).expect("branch workflow document");
        let sha = sha256_hex(&document).expect("document hash");
        let chunks: Vec<&str> = candidates.iter().map(String::as_str).collect();
        let input = build_chunk_input_for(&chunks);
        let input = parse_json_str(&input).expect("branch input document");
        let (machine, outcome) = start_run(
            document,
            &sha,
            format!("{}:{}", self.run_id, plan.account),
            input,
            1_000,
        )
        .expect("branch workflow must load");
        LiveBranch {
            account: plan.account.clone(),
            machine,
            outcome,
            finished: false,
        }
    }

    /// Advance one branch by one provider call (or drain pending effects).
    /// The ledger meters every call; budget exhaustion fails the branch loudly.
    fn step_one(&mut self, branch: &mut LiveBranch) {
        if branch.finished {
            return;
        }
        let effects = std::mem::take(&mut branch.outcome.effects);
        if effects.is_empty() {
            branch.outcome = branch.machine.tick(1_000);
            if branch.outcome.status.is_terminal() {
                branch.finished = true;
            } else if branch.outcome.effects.is_empty() {
                branch.finished = true; // stalled guard
            }
            if branch.finished {
                self.machine_events += branch.machine.events().len();
            }
            return;
        }
        for effect in effects {
            match effect {
                Effect::InvokeProvider {
                    invocation_id,
                    provider,
                    input,
                    ..
                } => {
                    let chunk = input
                        .get("chunk")
                        .and_then(Json::as_str)
                        .unwrap_or("?")
                        .to_string();
                    let chunk_text = input
                        .get("text")
                        .and_then(Json::as_str)
                        .unwrap_or("")
                        .to_string();
                    let tariff = self.tariffs.for_provider_name(&provider);
                    let reserve_key = format!(
                        "{}:{}:invoke:{}",
                        self.run_id, branch.account, invocation_id
                    );
                    match self
                        .ledger
                        .reserve(self.run_id, &branch.account, tariff, &reserve_key)
                    {
                        Ok(reservation_id) => {
                            match self.provider.analyze(&provider, &chunk, &chunk_text) {
                                Ok(answer) => {
                                    self.ledger
                                        .settle(
                                            reservation_id,
                                            tariff,
                                            &format!(
                                                "{}:{}:settle:{}",
                                                self.run_id, branch.account, invocation_id
                                            ),
                                        )
                                        .expect("settle of a live reservation");
                                    if answer.choice == "fynd" {
                                        self.found.insert(chunk.clone());
                                    }
                                    self.calls.push(CallRecord {
                                        account: branch.account.clone(),
                                        provider,
                                        chunk,
                                        choice: answer.choice.clone(),
                                        score_bp: answer.score_bp,
                                        cost_milli: tariff,
                                    });
                                    branch.outcome = branch.machine.complete(
                                        &invocation_id,
                                        Json::object([
                                            (
                                                "choice".to_string(),
                                                Json::from(answer.choice.as_str()),
                                            ),
                                            ("cache".to_string(), Json::from("miss")),
                                        ]),
                                        1_000,
                                    );
                                }
                                Err(error) => {
                                    // A provider failure is loud and free: the
                                    // reservation is released — nothing is charged
                                    // for a call that produced no answer.
                                    self.ledger
                                        .release(
                                            reservation_id,
                                            &format!(
                                                "{}:{}:release:{}",
                                                self.run_id, branch.account, invocation_id
                                            ),
                                        )
                                        .expect("release after provider failure");
                                    branch.outcome = branch.machine.fail(
                                        &invocation_id,
                                        RuntimeError::internal(format!("provider error: {error}")),
                                        1_000,
                                    );
                                    branch.finished = true;
                                }
                            }
                        }
                        Err(LedgerError::InsufficientFunds { .. }) => {
                            self.denied.push((branch.account.clone(), chunk));
                            branch.outcome = branch.machine.fail(
                                &invocation_id,
                                RuntimeError::limit(format!(
                                    "sweycoin budget exhausted for provider {provider:?}"
                                )),
                                1_000,
                            );
                            branch.finished = true;
                        }
                        Err(other) => {
                            self.denied.push((branch.account.clone(), chunk));
                            branch.outcome = branch.machine.fail(
                                &invocation_id,
                                RuntimeError::internal(format!("ledger error: {other}")),
                                1_000,
                            );
                            branch.finished = true;
                        }
                    }
                }
                Effect::InvokeHandler { invocation_id, .. } => {
                    branch.outcome = branch.machine.fail(
                        &invocation_id,
                        RuntimeError::unsupported("handlers are not part of the gym PoC"),
                        1_000,
                    );
                    branch.finished = true;
                }
                Effect::CancelInvocation { .. } => {
                    branch.outcome = branch.machine.cancel(1_000);
                    branch.finished = true;
                }
            }
        }
        if branch.finished {
            self.machine_events += branch.machine.events().len();
        }
    }
}
