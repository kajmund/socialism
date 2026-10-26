//! Teacher-student POC (docs/SWE_Sweycoins_v2.md 16): a small behavior-
//! cloning student trained on the adaptive pipeline's recorded decisions,
//! with leave-one-question-out as the mandatory first gate.
//!
//! The student is a multinomial logistic regression over facit-free
//! observation features -> the teacher's three actions
//! {Invest(A, 1000), Invest(B, 5000), Finish}. It must prove it can
//! imitate the teacher on a question it never saw before any RL is
//! layered on top. Terminal quality labels the episode, never the
//! individual decision — the credit-assignment problem is explicitly
//! out of scope for this gate (docs 16).

use crate::agent::Policy;
use crate::env::{Action, Observation};

// Feature vector over the facit-free interface. Every field is
// observable at decision time; nothing here touches the answer key.
pub const FEATURE_COUNT: usize = 11;

pub fn features(obs: &Observation) -> [f64; FEATURE_COUNT] {
    let pool_ratio = if obs.pool_total == 0 {
        0.0
    } else {
        obs.pool_scanned as f64 / obs.pool_total as f64
    };
    [
        obs.qtype as f64 / 4.0,
        obs.remaining_milli as f64 / 300_000.0,
        pool_ratio,
        (obs.found as f64 / 30.0).min(1.0),
        obs.new_evidence as f64,
        obs.recent_hit_rate_bp as f64 / 10_000.0,
        obs.last_score_bp as f64 / 10_000.0,
        obs.spent_milli[0] as f64 / 100_000.0,
        obs.spent_milli[1] as f64 / 100_000.0,
        obs.pool_extension_yielded as f64,
        obs.zero_hit_streak as f64 / 5.0,
    ]
}

/// The teacher's action vocabulary (the pipeline only ever takes these).
pub const CLASSES: [Action; 3] = [
    Action::Invest(0, 1_000),
    Action::Invest(1, 5_000),
    Action::Finish,
];

pub fn class_of(action: Action) -> usize {
    CLASSES.iter().position(|&a| a == action).unwrap_or(2) // unknown actions count as Finish
}

#[derive(Clone, Debug)]
pub struct StudentPolicy {
    /// (FEATURE_COUNT + 1) weights per class (bias included).
    w: Vec<f64>,
}

impl StudentPolicy {
    pub fn new() -> Self {
        Self {
            w: vec![0.0; (FEATURE_COUNT + 1) * CLASSES.len()],
        }
    }

    fn scores(&self, x: &[f64]) -> [f64; 3] {
        let mut s = [0.0f64; 3];
        for (c, sc) in s.iter_mut().enumerate() {
            let base = c * (FEATURE_COUNT + 1);
            *sc = self.w[base]; // bias
            for (i, xi) in x.iter().enumerate() {
                *sc += self.w[base + 1 + i] * xi;
            }
        }
        s
    }

    pub fn probs(&self, x: &[f64]) -> [f64; 3] {
        let s = self.scores(x);
        let max = s.iter().cloned().fold(f64::MIN, f64::max);
        let exps: Vec<f64> = s.iter().map(|v| (v - max).exp()).collect();
        let sum: f64 = exps.iter().sum();
        [exps[0] / sum, exps[1] / sum, exps[2] / sum]
    }

    pub fn predict(&self, obs: &Observation) -> usize {
        let x = features(obs);
        let p = self.probs(&x);
        let mut best = 0;
        for c in 1..3 {
            if p[c] > p[best] {
                best = c;
            }
        }
        best
    }

    /// Train on (features, class) pairs with SGD + softmax cross-entropy.
    pub fn train(pairs: &[(Vec<f64>, usize)], epochs: usize, lr: f64) -> Self {
        let mut student = Self::new();
        for _ in 0..epochs {
            for (x, y) in pairs {
                let p = student.probs(x);
                for c in 0..3 {
                    let target = if c == *y { 1.0 } else { 0.0 };
                    let base = c * (FEATURE_COUNT + 1);
                    student.w[base] += lr * (target - p[c]);
                    for (i, xi) in x.iter().enumerate() {
                        student.w[base + 1 + i] += lr * (target - p[c]) * xi;
                    }
                }
            }
        }
        student
    }
}

impl Policy for StudentPolicy {
    fn name(&self) -> &'static str {
        "student-bc"
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        let cls = self.predict(obs);
        let action = CLASSES[cls];
        if valid.contains(&action) {
            action
        } else {
            Action::Finish
        }
    }
}

use crate::dataset::Trajectory;

/// Extract (features, class) training pairs from the teacher's
/// trajectories: the recorded observation plus the recorded action.
pub fn teacher_pairs(trajectories: &[Trajectory]) -> Vec<(Vec<f64>, usize)> {
    let mut pairs = Vec::new();
    for t in trajectories {
        if t.policy != "real-pipeline-adaptive" {
            continue;
        }
        for step in &t.steps {
            pairs.push((features(&step.obs).to_vec(), class_of(step.action)));
        }
    }
    pairs
}

/// Leave-one-question-out: for each of the five questions, train on the
/// teacher trajectories of the other four and measure action agreement
/// over the held-out question's recorded states. Returns one agreement
/// per question (fold).
pub fn leave_one_out_gate(trajectories: &[Trajectory]) -> Vec<f64> {
    let question_ids: Vec<&str> = {
        let mut ids: Vec<&str> = trajectories
            .iter()
            .map(|t| t.question_id.as_str())
            .collect();
        ids.sort_unstable();
        ids.dedup();
        ids
    };
    let mut agreements = Vec::new();
    for held_out in &question_ids {
        let (train, test): (Vec<&Trajectory>, Vec<&Trajectory>) = trajectories
            .iter()
            .partition(|t| t.question_id != *held_out);
        let train_owned: Vec<Trajectory> = train.iter().map(|t| (*t).clone()).collect();
        let pairs = teacher_pairs(&train_owned);
        let student = StudentPolicy::train(&pairs, 400, 0.5);
        let mut hits = 0usize;
        let mut total = 0usize;
        for t in &test {
            if t.policy != "real-pipeline-adaptive" {
                continue;
            }
            for step in &t.steps {
                total += 1;
                if student.predict(&step.obs) == class_of(step.action) {
                    hits += 1;
                }
            }
        }
        agreements.push(hits as f64 / total as f64);
    }
    agreements
}
