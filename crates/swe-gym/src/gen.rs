//! Deterministic synthetic question generator for bandit training.
//!
//! Scripted data, by design: it measures whether a policy learns the budget
//! decision, never model quality. Every generated question needs escalation —
//! some evidence chunks are blind to the scan provider, so scan alone can
//! never reach the required coverage.

use std::collections::HashSet;

use crate::strategy::{Question, QuestionView};

const CHUNK_COUNT: usize = 10;

pub struct QuestionGenerator {
    state: u64,
    issued: usize,
}

impl QuestionGenerator {
    pub fn new(seed: u64) -> Self {
        Self {
            state: seed.max(1),
            issued: 0,
        }
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    fn below(&mut self, bound: u64) -> usize {
        (self.next_u64() % bound) as usize
    }

    /// Generate `count` questions: 10 chunks, 2..=5 evidence chunks, 1..=2 of
    /// them blind to the scan provider, required coverage = all evidence.
    pub fn generate(&mut self, count: usize) -> Vec<Question> {
        (0..count).map(|_| self.one()).collect()
    }

    /// Noisy variant for the generalization stress test: score model v2
    /// (per-question noise seed) and a per-question total budget of 20..40
    /// Sweycoins, so the affordable-deep-calls feature varies. Deterministic
    /// per generator seed.
    pub fn generate_noisy(&mut self, count: usize) -> Vec<Question> {
        (0..count).map(|_| self.one_noisy()).collect()
    }

    fn one_noisy(&mut self) -> Question {
        let mut question = self.one();
        question.noise_seed = 1 + self.next_u64();
        question.budget_milli = (20 + self.below(21)) as u64 * 1_000;
        question
    }

    /// Structured variant for the feature experiment: evidence lives only in
    /// the first half of the corpus (positions 0..5) — a scripted stand-in
    /// for real document structure. The scan position then carries real,
    /// facit-free information: a policy that reads it can stop scanning once
    /// the evidence region is behind it. Deterministic per generator seed.
    pub fn generate_structured_noisy(&mut self, count: usize) -> Vec<Question> {
        (0..count).map(|_| self.one_structured()).collect()
    }

    fn one_structured(&mut self) -> Question {
        let evidence_count = 2 + self.below(4); // 2..=5
        let blind_count = (1 + self.below(2)).min(evidence_count);
        let mut positions: Vec<usize> = Vec::new();
        while positions.len() < evidence_count {
            let position = self.below(5); // evidence region: first half
            if !positions.contains(&position) {
                positions.push(position);
            }
        }
        let chunks: Vec<String> = (0..CHUNK_COUNT).map(|i| format!("chunk-{i:02}")).collect();
        let evidence: HashSet<String> = positions
            .iter()
            .map(|position| chunks[*position].clone())
            .collect();
        let scan_blind: HashSet<String> = positions
            .iter()
            .take(blind_count)
            .map(|position| chunks[*position].clone())
            .collect();
        let id = format!("gen-struct-{:04}", self.issued);
        self.issued += 1;
        Question {
            view: QuestionView {
                id,
                chunks,
                required_coverage: evidence_count,
                question: String::new(),
                scan_order: Vec::new(),
            },
            evidence,
            scan_blind,
            noise_seed: 1 + self.next_u64(),
            budget_milli: (20 + self.below(21)) as u64 * 1_000,
            texts: std::collections::HashMap::new(),
        }
    }

    fn one(&mut self) -> Question {
        let evidence_count = 2 + self.below(4); // 2..=5
        let blind_count = (1 + self.below(2)).min(evidence_count); // 1..=2
        let mut positions: Vec<usize> = Vec::new();
        while positions.len() < evidence_count {
            let position = self.below(CHUNK_COUNT as u64);
            if !positions.contains(&position) {
                positions.push(position);
            }
        }
        let chunks: Vec<String> = (0..CHUNK_COUNT).map(|i| format!("chunk-{i:02}")).collect();
        let evidence: HashSet<String> = positions
            .iter()
            .map(|position| chunks[*position].clone())
            .collect();
        let scan_blind: HashSet<String> = positions
            .iter()
            .take(blind_count)
            .map(|position| chunks[*position].clone())
            .collect();
        let id = format!("gen-{:04}", self.issued);
        self.issued += 1;
        Question {
            view: QuestionView {
                id,
                chunks,
                required_coverage: evidence_count,
                question: String::new(),
                scan_order: Vec::new(),
            },
            evidence,
            scan_blind,
            noise_seed: 0,
            budget_milli: 0,
            texts: std::collections::HashMap::new(),
        }
    }
}
