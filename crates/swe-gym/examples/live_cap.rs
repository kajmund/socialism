//! Live cap experiment — the strategy document's first experiment, section 11:
//! instrument JEV calls with a fixed test tariff and verify that parallel
//! calls under a cap cannot charge more than the cap.
//!
//! Eight threads each try one metered JEV call; the run cap is 2 Sweycoins at
//! a tariff of 1 per call. Exactly two calls may run — the rest are denied
//! loudly by the ledger. The ledger lock is never held across the HTTP call.
//!
//! Usage: cargo run --example live_cap   (costs up to 2 small JEV calls)

use std::sync::{Arc, Mutex};

use swe_gym::ledger::Ledger;
use swe_gym::provider::{resolve_secret, HttpJevProvider, ResearchProvider};

const CALLS: usize = 8;
const CAP_MILLI: u64 = 2_000;
const TARIFF_MILLI: u64 = 1_000;

fn main() {
    let api_key = resolve_secret("TYPESAFE_API_KEY", "../../backend/.env")
        .expect("TYPESAFE_API_KEY saknas (sätt i miljön eller backend/.env)");
    let base_url = resolve_secret("TYPESAFE_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.typesafe.ai".to_string());
    let model = resolve_secret("JEV_MODEL", "../../backend/.env")
        .unwrap_or_else(|| "jev-latest".to_string());
    let provider = Arc::new(HttpJevProvider::new(&api_key, &base_url, &model));

    let ledger = Arc::new(Mutex::new(Ledger::new()));
    {
        let mut guard = ledger.lock().unwrap();
        guard
            .allocate("live-cap", "root", CAP_MILLI, "live-cap:alloc")
            .unwrap();
    }

    let handles: Vec<_> = (0..CALLS)
        .map(|i| {
            let ledger = Arc::clone(&ledger);
            let provider = Arc::clone(&provider);
            std::thread::spawn(move || {
                let chunk = format!("chunk-{i:02}");
                let text = if i % 2 == 0 {
                    "Styrelsen får förlänga avtalet automatiskt utan nytt godkännande."
                } else {
                    "Part ska betala faktura inom trettio dagar från fakturadatum."
                };
                // Reserve fast, release the lock, call the external service,
                // then settle in a new critical section.
                let reservation = {
                    let mut guard = ledger.lock().unwrap();
                    guard.reserve(
                        "live-cap",
                        "root",
                        TARIFF_MILLI,
                        &format!("live-cap:invoke:{chunk}"),
                    )
                };
                match reservation {
                    Ok(reservation) => {
                        let answer = provider
                            .analyze("scan", &chunk, text)
                            .expect("JEV must answer or fail loudly");
                        let mut guard = ledger.lock().unwrap();
                        guard
                            .settle(
                                reservation,
                                TARIFF_MILLI,
                                &format!("live-cap:settle:{chunk}"),
                            )
                            .unwrap();
                        format!(
                            "{chunk}: KÖRDE  {:<6} score {:<5}",
                            answer.choice, answer.score_bp
                        )
                    }
                    Err(_) => format!("{chunk}: NEKAD — budget uttömd"),
                }
            })
        })
        .collect();

    let mut ran = 0;
    for handle in handles {
        let line = handle.join().unwrap();
        println!("{line}");
        if line.contains("KÖRDE") {
            ran += 1;
        }
    }

    let guard = ledger.lock().unwrap();
    let balance = guard.balance("root");
    println!(
        "cap {} / körde {} / spenderat {} / kvar {}",
        format_amount(CAP_MILLI),
        ran,
        format_amount(balance.spent),
        format_amount(balance.available()),
    );
    assert_eq!(ran, 2, "exactly the cap allows two calls");
    assert_eq!(balance.spent, CAP_MILLI);
    let replayed = Ledger::replay(guard.events()).expect("event log must replay");
    assert_eq!(
        replayed.balances(),
        guard.balances(),
        "replay must match live"
    );
    println!("replay == live: true");
}

fn format_amount(milli: u64) -> String {
    format!("{}.{:03}", milli / 1_000, milli % 1_000)
}
