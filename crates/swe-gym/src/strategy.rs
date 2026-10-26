//! Strategy interface and the first two arms: sequential priority (A) and
//! parallel with equal start budget (B).
//!
//! Facit isolation is enforced by the type system: strategies receive only
//! `QuestionView` (chunk ids + required coverage). The corpus answer table
//! lives in `FakeCorpus`, which only the harness/evaluator may touch.

use std::collections::{HashMap, HashSet};

use crate::ledger::Amount;

/// What a strategy is allowed to see: the question without its answer key.
#[derive(Clone, Debug, PartialEq)]
pub struct QuestionView {
    pub id: String,
    pub chunks: Vec<String>,
    pub required_coverage: usize,
}

/// A benchmark question: view (visible to strategies) plus the facit.
#[derive(Clone, Debug, PartialEq)]
pub struct Question {
    pub view: QuestionView,
    /// Ground truth: chunks that contain evidence. Harness/evaluator only.
    pub evidence: HashSet<String>,
    /// Chunks the scan provider cannot see (its blind spot).
    pub scan_blind: HashSet<String>,
    /// Score-model noise seed. 0 = score model v1 (exact, frozen). Nonzero =
    /// v2: per-chunk deterministic noise, so blind evidence sometimes scores
    /// below negatives and negatives sometimes look suspicious.
    pub noise_seed: u64,
    /// Per-question total budget in milli-Sweycoins; 0 = the caller's budget.
    pub budget_milli: u64,
}

impl Question {
    pub fn corpus(&self) -> FakeCorpus {
        FakeCorpus {
            evidence: self.evidence.clone(),
            scan_blind: self.scan_blind.clone(),
            noise_seed: self.noise_seed,
        }
    }
}

/// The simulated world the fake providers answer from. Scan is imperfect
/// (blind to some chunks); deep is perfect.
///
/// Providers emit both a binary choice and a confidence score (basis points,
/// 0..10_000). The score is ordinary provider metadata — correlated with the
/// truth, exactly like a real model's confidence, but not the answer key
/// itself. Strategies may observe scores; they may never observe `evidence`.
///
/// Score model v1 (noise_seed = 0) is frozen and exact: evidence 9000, blind
/// evidence 4500 (suspicious, just below the 5000 threshold), negatives 1000.
/// Score model v2 (noise_seed != 0) adds deterministic per-chunk noise: blind
/// evidence ranges ~500..5500 and negatives ~0..3500, so they overlap — the
/// ranking signal becomes genuinely ambiguous.
#[derive(Clone, Debug)]
pub struct FakeCorpus {
    evidence: HashSet<String>,
    scan_blind: HashSet<String>,
    noise_seed: u64,
}

impl FakeCorpus {
    /// Deterministic unit noise in [-1, 1] per (noise_seed, chunk, salt).
    /// Zero when the corpus uses the frozen v1 model.
    fn unit_noise(&self, chunk: &str, salt: u64) -> f64 {
        if self.noise_seed == 0 {
            return 0.0;
        }
        let mut x = self.noise_seed ^ salt;
        for byte in chunk.bytes() {
            x = x
                .wrapping_mul(0x0000_0100_0000_01b3)
                .wrapping_add(u64::from(byte));
        }
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        let unit = (x >> 11) as f64 / (1u64 << 53) as f64;
        unit * 2.0 - 1.0
    }

    /// Scan confidence: v1 exact; v2 noisy with the overlap described above.
    pub fn scan_score(&self, chunk: &str) -> u32 {
        if self.noise_seed == 0 {
            return if self.evidence.contains(chunk) {
                if self.scan_blind.contains(chunk) {
                    4_500
                } else {
                    9_000
                }
            } else {
                1_000
            };
        }
        let score = if self.evidence.contains(chunk) {
            if self.scan_blind.contains(chunk) {
                3_000.0 + self.unit_noise(chunk, 1) * 2_500.0
            } else {
                9_000.0 + self.unit_noise(chunk, 2) * 1_500.0
            }
        } else {
            1_000.0 + self.unit_noise(chunk, 3) * 2_500.0
        };
        score.round().clamp(0.0, 10_000.0) as u32
    }

    pub fn scan(&self, chunk: &str) -> bool {
        self.scan_score(chunk) >= 5_000
    }

    pub fn deep_score(&self, chunk: &str) -> u32 {
        if self.evidence.contains(chunk) {
            9_900
        } else {
            200
        }
    }

    pub fn deep(&self, chunk: &str) -> bool {
        self.evidence.contains(chunk)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProviderKind {
    Scan,
    Deep,
}

impl ProviderKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Scan => "scan",
            Self::Deep => "deep",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Tariffs {
    pub scan_milli: Amount,
    pub deep_milli: Amount,
}

impl Tariffs {
    pub fn for_provider_name(self, provider: &str) -> Amount {
        match provider {
            "scan" => self.scan_milli,
            "deep" => self.deep_milli,
            other => panic!("unknown provider {other:?} in tariff table"),
        }
    }
}

#[derive(Clone, Debug)]
pub struct BranchPlan {
    pub account: String,
    pub provider: ProviderKind,
    pub chunks: Vec<String>,
    pub start_budget_milli: Amount,
}

/// How the harness executes a strategy's plans. The continuation rules are
/// deterministic and shared, so arms differ only where the experiment says
/// they differ.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Continuation {
    /// Run branches in plan order; escalate only if coverage is still
    /// insufficient; escalation targets chunks not yet found, in plan order;
    /// leftover budget flows to the next branch.
    Sequential,
    /// Run all branches interleaved round-robin; a finished branch's leftover
    /// budget is transferred to the first still-live branch.
    ParallelEqual,
}

/// Per-scan-step decision during the scan phase: keep scanning or stop and
/// escalate to the deep phase. The sequential-RL decision of the strategy
/// document.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScanDecision {
    Continue,
    Escalate,
}

/// Facit-free state at a scan checkpoint: what the strategy may observe
/// before each continue/escalate decision.
#[derive(Clone, Debug)]
pub struct ScanState {
    pub scanned: usize,
    pub remaining: usize,
    pub found: usize,
    pub required: usize,
    pub last_choice: String,
    pub last_score_bp: u32,
    pub best_score_bp: u32,
}

pub trait Strategy {
    fn name(&self) -> &'static str;

    /// Diagnostic strategies (e.g. the oracle arm) must never count as
    /// contenders: their reports are ceilings, not candidates.
    fn diagnostic(&self) -> bool {
        false
    }

    fn plan(
        &self,
        view: &QuestionView,
        total_budget_milli: Amount,
        tariffs: &Tariffs,
    ) -> Vec<BranchPlan>;
    fn continuation(&self) -> Continuation;

    /// Optional per-scan-step hook: after each completed scan call the
    /// strategy may stop the scan phase and escalate. The default keeps
    /// scanning — exactly arm A/C behavior. This is the second decision point
    /// a learned policy plugs into.
    fn observe_scan(&mut self, _state: &ScanState) -> ScanDecision {
        ScanDecision::Continue
    }

    /// Optional revision hook: after a branch has finished, the strategy may
    /// reorder or reshape its remaining plans based on facit-free
    /// observations (findings, provider scores, budgets). This is the
    /// decision point a learned policy plugs into: state in, budget proposal
    /// out. The default keeps the plan untouched — that is exactly arm A's
    /// behavior.
    fn revise(
        &mut self,
        _finished_index: usize,
        _observations: &Observations,
        _plans: &mut [BranchPlan],
        _tariffs: &Tariffs,
    ) {
    }
}

/// What a strategy may learn between branches: findings, provider confidence
/// and the coverage target — never the answer key.
#[derive(Clone, Debug)]
pub struct Observations {
    pub found: Vec<String>,
    pub required: usize,
    /// (chunk, score_bp) for every completed scan call.
    pub scan_scores: Vec<(String, u32)>,
}

/// Rank unresolved chunks by scan confidence, closest to the decision boundary
/// first; ties keep document order. Facit-free: provider scores only.
pub fn rank_unresolved_by_score(plan: &BranchPlan, observations: &Observations) -> Vec<String> {
    let mut scores: HashMap<String, u32> = observations.scan_scores.iter().cloned().collect();
    let mut ranked: Vec<(std::cmp::Reverse<u32>, usize, String)> = plan
        .chunks
        .iter()
        .enumerate()
        .filter(|(_, chunk)| !observations.found.contains(*chunk))
        .map(|(position, chunk)| {
            (
                std::cmp::Reverse(scores.remove(chunk).unwrap_or(0)),
                position,
                chunk.clone(),
            )
        })
        .collect();
    ranked.sort();
    ranked.into_iter().map(|(_, _, chunk)| chunk).collect()
}

/// Arm A: deterministic-first. Scan everything in document order; escalate to
/// deep analysis only if coverage is still insufficient.
pub struct SequentialStrategy;

impl Strategy for SequentialStrategy {
    fn name(&self) -> &'static str {
        "A sekventiell"
    }

    fn plan(
        &self,
        view: &QuestionView,
        total_budget_milli: Amount,
        tariffs: &Tariffs,
    ) -> Vec<BranchPlan> {
        let scan_cost = tariffs
            .scan_milli
            .saturating_mul(view.chunks.len() as Amount);
        let scan_budget = scan_cost.min(total_budget_milli);
        vec![
            BranchPlan {
                account: "a-scan".into(),
                provider: ProviderKind::Scan,
                chunks: view.chunks.clone(),
                start_budget_milli: scan_budget,
            },
            BranchPlan {
                account: "a-deep".into(),
                provider: ProviderKind::Deep,
                chunks: view.chunks.clone(),
                start_budget_milli: total_budget_milli - scan_budget,
            },
        ]
    }

    fn continuation(&self) -> Continuation {
        Continuation::Sequential
    }
}

/// Arm B: split the budget equally and run both paths at once. The deep branch
/// walks the corpus in reverse order; the deterministic continuation rule
/// moves a finished branch's leftover to the still-live branch.
pub struct ParallelEqualStrategy;

impl Strategy for ParallelEqualStrategy {
    fn name(&self) -> &'static str {
        "B parallell lika budget"
    }

    fn plan(
        &self,
        view: &QuestionView,
        total_budget_milli: Amount,
        _tariffs: &Tariffs,
    ) -> Vec<BranchPlan> {
        let half = total_budget_milli / 2;
        let mut reversed = view.chunks.clone();
        reversed.reverse();
        vec![
            BranchPlan {
                account: "b-scan".into(),
                provider: ProviderKind::Scan,
                chunks: view.chunks.clone(),
                start_budget_milli: half,
            },
            BranchPlan {
                account: "b-deep".into(),
                provider: ProviderKind::Deep,
                chunks: reversed,
                start_budget_milli: total_budget_milli - half,
            },
        ]
    }

    fn continuation(&self) -> Continuation {
        Continuation::ParallelEqual
    }
}

/// Arm C: adaptive escalation. Identical plan to arm A (scan first, escalate
/// only if needed) — the single changed variable is the revision rule: the
/// deep branch targets unresolved chunks by scan confidence, closest to the
/// decision boundary first. Ties keep document order (stable sort), so the
/// arm stays deterministic.
pub struct AdaptiveStrategy;

impl Strategy for AdaptiveStrategy {
    fn name(&self) -> &'static str {
        "C adaptiv"
    }

    fn plan(
        &self,
        view: &QuestionView,
        total_budget_milli: Amount,
        tariffs: &Tariffs,
    ) -> Vec<BranchPlan> {
        let scan_cost = tariffs
            .scan_milli
            .saturating_mul(view.chunks.len() as Amount);
        let scan_budget = scan_cost.min(total_budget_milli);
        vec![
            BranchPlan {
                account: "c-scan".into(),
                provider: ProviderKind::Scan,
                chunks: view.chunks.clone(),
                start_budget_milli: scan_budget,
            },
            BranchPlan {
                account: "c-deep".into(),
                provider: ProviderKind::Deep,
                chunks: view.chunks.clone(),
                start_budget_milli: total_budget_milli - scan_budget,
            },
        ]
    }

    fn continuation(&self) -> Continuation {
        Continuation::Sequential
    }

    fn revise(
        &mut self,
        finished_index: usize,
        observations: &Observations,
        plans: &mut [BranchPlan],
        _tariffs: &Tariffs,
    ) {
        if finished_index != 0 {
            return;
        }
        let Some(deep) = plans.get_mut(1) else {
            return;
        };
        deep.chunks = rank_unresolved_by_score(deep, observations);
    }
}

/// C* (diagnostic only): an oracle with facit-derived guidance. Its single
/// purpose is to bound how much adaptivity could ever help — the cost floor
/// of the task. It must never contribute reported answers or count as a
/// contender.
///
/// The facit enters through the constructor: a deliberate, documented breach
/// of the QuestionView isolation, visible in one place.
pub struct OracleStrategy {
    /// Evidence chunks in document order, split by what the scan provider can
    /// see.
    visible: Vec<String>,
    hidden: Vec<String>,
}

impl OracleStrategy {
    pub fn new(question: &Question) -> Self {
        let evidence_in_order: Vec<String> = question
            .view
            .chunks
            .iter()
            .filter(|chunk| question.evidence.contains(*chunk))
            .cloned()
            .collect();
        let visible = evidence_in_order
            .iter()
            .filter(|chunk| !question.scan_blind.contains(*chunk))
            .cloned()
            .collect();
        let hidden = evidence_in_order
            .iter()
            .filter(|chunk| question.scan_blind.contains(*chunk))
            .cloned()
            .collect();
        Self { visible, hidden }
    }
}

impl Strategy for OracleStrategy {
    fn name(&self) -> &'static str {
        "C* orakel (diagnostik)"
    }

    fn diagnostic(&self) -> bool {
        true
    }

    fn plan(
        &self,
        view: &QuestionView,
        total_budget_milli: Amount,
        tariffs: &Tariffs,
    ) -> Vec<BranchPlan> {
        // Perfect knowledge, minimal cost: scan exactly as many visible
        // evidence chunks as the question needs, then deep-analyze exactly the
        // remaining hidden ones. Everything else is skipped.
        let needed = view.required_coverage;
        let scan_take = needed.min(self.visible.len());
        let visible: Vec<String> = self.visible.iter().take(scan_take).cloned().collect();
        let deep_take = needed.saturating_sub(scan_take);
        let hidden: Vec<String> = self.hidden.iter().take(deep_take).cloned().collect();
        let scan_cost = tariffs
            .scan_milli
            .saturating_mul(visible.len() as Amount)
            .min(total_budget_milli);
        vec![
            BranchPlan {
                account: "cx-scan".into(),
                provider: ProviderKind::Scan,
                chunks: visible,
                start_budget_milli: scan_cost,
            },
            BranchPlan {
                account: "cx-deep".into(),
                provider: ProviderKind::Deep,
                chunks: hidden,
                start_budget_milli: total_budget_milli - scan_cost,
            },
        ]
    }

    fn continuation(&self) -> Continuation {
        Continuation::Sequential
    }
}
