//! SWE Gym v2 — synergy world (docs/SWE_Sweycoins_v2.md 13): the final
//! synthetic experiment, complementary capabilities with delayed return.
//!
//! A = retrieval (zero direct quality, unlocks JEV), B = JEV (4x cost
//! without A), C = LLM (can only synthesize what B extracted). The
//! learner must discover "A first" on chain types and "skip A" where
//! retrieval does not pay.
//!
//! Pipeline: online season -> coverage sweep -> offline replay fit.
//! Run with: cargo run --example v2_synergy

use swe_gym::agent::{McQLearner, Policy};
use swe_gym::env::{synergy_config, Question, SweEnv, SyntheticEnv};
use swe_gym::oracle::{oracle_policy_cost, oracle_value};
use swe_gym::train::{calibration_gate, default_question_sets, evaluate, run_episode, run_season};

fn train_learner(seed: u64) -> McQLearner {
    let config = synergy_config();
    let mut learner = McQLearner::new(seed);
    let mut train = Vec::new();
    for qtype in 0..4u8 {
        for i in 0..200u32 {
            train.push(Question {
                id: format!("t{qtype}-{i}"),
                qtype,
                budget_milli: 100_000,
            });
        }
    }
    run_season(&config, &mut learner, &train);
    learner.set_sweep(true);
    let mut sweep = Vec::new();
    for qtype in 0..4u8 {
        for i in 0..400u32 {
            sweep.push(Question {
                id: format!("s{qtype}-{i}"),
                qtype,
                budget_milli: 100_000,
            });
        }
    }
    run_season(&config, &mut learner, &sweep);
    learner.set_sweep(false);
    learner.replay_fit(100);
    learner.set_eval(true);
    learner
}

fn main() {
    let config = synergy_config();
    let (_train, held_out) = default_question_sets();

    println!("== SWE Gym v2 — synergy world (delayed return) ==");
    println!("A=retrieval (0 direct quality, unlocks B)  B=JEV (4x cost without A)  C=LLM (gated by B)\n");

    let gate = calibration_gate(&config, &held_out);
    println!("-- calibration gate --");
    for (name, mean) in [
        ("equal-split", gate.baseline_means[0]),
        ("sequential (pipeline)", gate.baseline_means[1]),
        ("adaptive (plateau)", gate.baseline_means[2]),
    ] {
        println!("  {name:<22} {:>9.0}", mean);
    }
    println!("  {:<22} {:>9.0}", "oracle", gate.oracle_mean);
    println!(
        "  gate: {} (ratio {:.2})\n",
        if gate.passed { "PASS" } else { "FAIL" },
        gate.margin_ratio
    );

    let mut learner = train_learner(7);
    let learner_mean = evaluate(&config, &mut learner, &held_out);
    println!("-- held-out --");
    println!("  mc-q-learner (online+sweep+replay) {:>9.0}", learner_mean);
    println!(
        "  learner / oracle = {:.2}   learner / best baseline = {:.2}\n",
        learner_mean / gate.oracle_mean,
        learner_mean / gate.best_baseline_mean
    );

    println!("-- stop decision --");
    let mut lc = 0u64;
    let mut oc = 0u64;
    for (i, q) in held_out.iter().enumerate() {
        lc += run_episode(&config, &mut learner, q, i as u64).spent_milli;
        oc += oracle_policy_cost(&config, q.qtype, q.budget_milli);
    }
    println!(
        "  learner spend {lc}   oracle optimal {oc}   ratio {:.2} (acceptance <= 1.5)\n",
        lc as f64 / oc as f64
    );

    println!("-- delayed-return discovery (first investment per type) --");
    for q in held_out.iter().take(4) {
        let mut env = SyntheticEnv::new(config.clone());
        env.reset(q).unwrap();
        learner.episode_start(q, 0);
        let valid = env.valid_actions();
        let first = learner.act(env.observation(), &valid);
        let report = run_episode(&config, &mut learner, q, 0);
        println!(
            "  {:<20} first {:?}   net {:>7}   (oracle {})",
            q.id,
            first,
            report.reward_milli,
            oracle_value(&config, q.qtype, q.budget_milli)
        );
    }
    println!("\n(no facit in the observation; quality is revealed only at episode end.)");
}
