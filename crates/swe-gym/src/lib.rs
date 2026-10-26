//! swe-gym: Sweycoin budget experiment (PoC stage).
//!
//! Ledger + metered driver on top of the swe-native kernel. No external
//! services. See AGENTS.md in this directory for experiment governance.

pub mod agent;
pub mod bandit;
pub mod bench;
pub mod benchmark;
pub mod calibrate;
pub mod driver;
pub mod env;
pub mod gen;
pub mod ledger;
pub mod oracle;
pub mod provider;
pub mod strategy;
pub mod td;
pub mod train;
