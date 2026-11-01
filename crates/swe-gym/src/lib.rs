//! swe-gym: Sweycoin budget experiment (PoC stage).
//!
//! Ledger + metered driver on top of the swe-native kernel. No external
//! services. See AGENTS.md in this directory for experiment governance.

pub mod agent;
pub mod bandit;
pub mod bench;
pub mod benchmark;
pub mod calibrate;
pub mod dataset;
pub mod driver;
pub mod env;
pub mod explore;
pub mod gen;
/// The Sweycoin ledger moved to `swe-budget` (B2). Re-exported so the
/// experiment keeps one implementation.
pub mod ledger {
    pub use swe_budget::*;
}
pub mod ops;
pub mod oracle;
pub mod provider;
pub mod real;
pub mod strategy;
pub mod student;
pub mod td;
pub mod train;
